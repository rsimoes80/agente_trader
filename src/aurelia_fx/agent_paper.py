"""Paper execution on observed bid/ask quotes, never retrospective bar opens."""

from __future__ import annotations

import copy
import math
from datetime import datetime, timedelta, timezone

from .agent_model import PROTOCOL, fingerprint
from .domain import AccountSnapshot, Candidate, DataQuality, RiskLimits
from .historical.core import utc
from .risk import assess_candidate
from .source_clock import validate_source_clock

LIMITS = RiskLimits(0.5, 2, 5, 2, 2, 5)
COMMISSION = 35 / 1_000_000
SLIPPAGE = 0.00002


def observed_quote(data, *, clock_id, now=None, symbol=None):
    if symbol is not None and data.get('symbol')!=symbol:
        raise ValueError('QUOTE_INSTRUMENT_MISMATCH')
    now = now or datetime.now(timezone.utc)
    clock = validate_source_clock(data, now)
    if clock["clock_id"] != clock_id:
        raise ValueError(
            "A fonte mudou; a sessão precisa de reconciliação antes de continuar."
        )
    quote = data.get("quote") or {}
    bid, ask = quote.get("bid"), quote.get("ask")
    if (
        not all(
            isinstance(x, (int, float)) and math.isfinite(x) and x > 0
            for x in (bid, ask)
        )
        or ask < bid
    ):
        raise ValueError("Cotação bid/ask inválida.")
    at = utc(quote["time"])
    if abs((at - utc(clock["tick_utc"])).total_seconds()) > 1:
        raise ValueError("A cotação não corresponde ao relógio validado.")
    return dict(bid=bid, ask=ask, at=at.isoformat(), observed_at=now.isoformat())


class PaperAccount:
    def __init__(
        self,
        session_id,
        lot,
        contract,
        model_id,
        clock_id,
        *,
        checkpoint=None,
        previous_account=None,
        research_mode=False,
        profile=None,
    ):
        self._research_profile=profile
        if profile:profile.execution_config(float(lot))
        self._price_unit=profile.price_unit if profile else .0001
        self._slippage=profile.costs.slippage_price if profile else SLIPPAGE
        self._fee_per_value_unit=profile.costs.commission_per_lot_side/profile.value_per_price_per_lot if profile else COMMISSION
        self._limits=RiskLimits(.5,2,5,profile.max_spread_units,2,5) if profile else LIMITS
        self.validate_contract(contract)
        self.data = dict(
            version="observed-paper-v1",
            session_id=session_id,
            lot=lot,
            model_id=model_id,
            clock_id=clock_id,
            units=float(lot) * (profile.value_per_price_per_lot if profile else contract["contract_size"]),
            balance=PROTOCOL["initial_equity"],
            peak=PROTOCOL["initial_equity"],
            day_start=PROTOCOL["initial_equity"],
            day=None,
            daily_entries=0,
            closed_trades=0,
            wins=0,
            losses=0,
            uncertain_trades=0,
            realized_today=0,
            position=None,
            last_quote=None,
            last_candle=None,
            quote_basis="sampled_bid_ask; stops react to observed quotes; gaps flagged",
            commission_assumption_per_million_side=35,
            slippage_assumption_pips=0.2,
        )
        if profile:
            self.data.update(symbol=profile.symbol,profile_id=profile.fingerprint,
                research_profile=profile.as_dict(),price_unit=profile.price_unit,
                commission_assumption_per_million_side=None,slippage_assumption_pips=self._slippage/self._price_unit)
        if checkpoint:
            if profile and (checkpoint.get('profile_id')!=profile.fingerprint or checkpoint.get('symbol')!=profile.symbol):
                raise ValueError('PAPER_STUDY_INSTRUMENT_MISMATCH')
            if any(
                checkpoint.get(k) != self.data[k]
                for k in (
                    "version",
                    "session_id",
                    "lot",
                    "model_id",
                    "clock_id",
                    "units",
                )
            ):
                raise ValueError(
                    "Checkpoint de posição incompatível. Não será descartado."
                )
            self.data = copy.deepcopy(checkpoint)
        elif previous_account:
            if previous_account.get("position"):
                raise ValueError(
                    "Há posição em outra sessão. A conta simulada precisa ser reconciliada."
                )
            for key in (
                "balance",
                "peak",
                "day_start",
                "day",
                "daily_entries",
                "closed_trades",
                "wins",
                "losses",
                "uncertain_trades",
                "realized_today",
                "last_candle",
            ):
                self.data[key] = copy.deepcopy(previous_account[key])
        self.events = []
        if checkpoint and bool(checkpoint.get("research_mode",False)) != research_mode:
            raise ValueError("O modo de pesquisa não corresponde ao checkpoint.")
        self.data["research_mode"] = research_mode
        if "lab_state" not in self.data:
            self.data["lab_state"] = copy.deepcopy((previous_account or {}).get("lab_state",{}))
        if research_mode:
            self.data["lab_state"].setdefault("protocol_id",model_id)

    def validate_contract(self,contract):
        if self._research_profile:
            p=self._research_profile
            if contract.get('symbol')!=p.symbol or contract.get('contract_size')!=p.contract.contract_size or contract.get('currency_profit')!=p.contract.currency_profit:
                raise ValueError('PAPER_STUDY_CONTRACT_MISMATCH')
            return
        if contract.get('currency_profit')!='USD' or contract.get('contract_size',0)<=0:
            raise ValueError('A conta simulada requer contrato EURUSD em USD.')

    def snapshot(self):
        return copy.deepcopy(self.data)

    def event(self, kind, at, **fields):
        event = dict(
            session_id=self.data["session_id"],
            mode="paper_research" if self.data["research_mode"] else "paper",
            status=kind,
            at=at,
            model_id=self.data["model_id"],
            **fields,
        )
        if self._research_profile:event.update(symbol=self._research_profile.symbol,profile_id=self._research_profile.fingerprint)
        event["event_id"] = fingerprint(event)
        self.events.append(event)
        return event

    def equity(self, quote):
        p = self.data["position"]
        if not p:
            return self.data["balance"]
        exit_price = quote["bid"] if p["side"] == "long" else quote["ask"]
        return (
            self.data["balance"]
            + p["sign"] * (exit_price - p["entry"]) * p["units"]
            - 2 * self._fee_per_value_unit * p["units"]
        )

    def mark(self, quote, *, force_close=None):
        at = utc(quote.get("observed_at", quote["at"]))
        from .entry_trend import POLICY_ID, STRICT_POLICY_ID
        if POLICY_ID != STRICT_POLICY_ID:
            from .daytrade import closing_reason
            force_close=force_close or closing_reason(at,profile=self._research_profile)
        if self._research_profile and not self._research_profile.allows_entry(at):force_close=force_close or 'CALENDAR_CLOSE'
        previous = self.data["last_quote"]
        if previous and at < utc(previous.get("observed_at", previous["at"])):
            raise ValueError("A conta simulada não pode voltar no tempo.")
        day = at.date().isoformat()
        if self.data["day"] != day:
            self.data.update(
                day=day, day_start=self.equity(quote), daily_entries=0, realized_today=0
            )
        p = self.data["position"]
        if p:
            if (
                previous
                and (
                    at - utc(previous.get("observed_at", previous["at"]))
                ).total_seconds()
                > 30
            ):
                p["coverage_uncertain"] = True
            price = quote["bid"] if p["side"] == "long" else quote["ask"]
            stop = price <= p["stop"] if p["sign"] == 1 else price >= p["stop"]
            target = price >= p["target"] if p["sign"] == 1 else price <= p["target"]
            expired = at >= utc(p["entry_at"]) + timedelta(hours=1)
            reason = force_close or (
                "STOP_OBSERVED"
                if stop
                else "TARGET_OBSERVED"
                if target
                else "TIME_LIMIT"
                if expired
                else None
            )
            if reason:
                fill = price - p["sign"] * self._slippage
                commission = 2 * self._fee_per_value_unit * p["units"]
                net = p["sign"] * (fill - p["entry"]) * p["units"] - commission
                self.data["balance"] += net
                self.data["realized_today"] += net
                self.data["closed_trades"] += 1
                self.data["wins"] += int(net > 0)
                self.data["losses"] += int(net < 0)
                self.data["uncertain_trades"] += int(p["coverage_uncertain"])
                self.event(
                    "closed",
                    at.isoformat(),
                    decision_id=p["decision_id"],
                    position=copy.deepcopy(p),
                    exit_price=fill,
                    reason=reason,
                    net_pnl=net,
                    commission=commission,
                    result_in_r=net / p["initial_risk"],
                    learning_eligible=False,
                    research_reward_eligible=bool(self.data["research_mode"] and not p["coverage_uncertain"]),
                    reward_scope="observed_paper_experiment" if self.data["research_mode"] else None,
                    label_scope="paper_quote_sampling_not_verified_tick_path",
                    execution_basis="observed_quote_not_guaranteed_broker_fill",
                )
                if self.data["research_mode"]:
                    from .autonomous_lab import learn
                    learn(self.data["lab_state"],p,net,net/p["initial_risk"])
                self.data["position"] = None
        self.data["last_quote"] = dict(quote)
        self.data["peak"] = max(self.data["peak"], self.equity(quote))

    def open(self, setup, features, probability, quote, *, active_sessions, hypothesis=None):
        from .entry_trend import POLICY_ID, STRICT_POLICY_ID
        if POLICY_ID != STRICT_POLICY_ID:
            from .daytrade import closing_reason
            reason=closing_reason(quote.get('observed_at',quote['at']),profile=self._research_profile)
            if reason:return dict(approved=False,reasons=[reason])
        if self._research_profile and setup.get('snapshot',{}).get('symbol')!=self._research_profile.symbol:
            raise ValueError('PAPER_STUDY_INSTRUMENT_MISMATCH')
        from .entry_trend import entry_blocker
        blocker = entry_blocker(setup.get("snapshot"), setup["candidate"].side)
        if blocker:
            return dict(approved=False, reasons=[blocker])
        if self.data["position"]:
            raise ValueError("Já existe posição simulada.")
        if self.data["research_mode"] and not hypothesis:
            raise ValueError("Experimento sem hipótese identificada.")
        if self.data["research_mode"]:
            from .autonomous_lab import HYPOTHESES
            if hypothesis.get("protocol_id") != self.data["model_id"] or hypothesis.get("id") not in dict(HYPOTHESES) or not hypothesis.get("context"):
                raise ValueError("Hipótese incompatível com o protocolo de pesquisa.")
        if not self.data["research_mode"] and not setup.get("production_eligible"):
            return dict(approved=False, reasons=["CONTEXT_NOT_OPERATIONALLY_ELIGIBLE"])
        if ((probability is None and not self.data["research_mode"])
            or (probability is not None and (not math.isfinite(probability) or not 0 <= probability <= 1))):
            raise ValueError("Probabilidade inválida.")
        self.mark(quote)
        original = setup["candidate"]
        sign = 1 if original.side == "long" else -1
        if self._research_profile and not self._research_profile.allows_entry(utc(quote.get('observed_at',quote['at']))):
            return dict(approved=False,reasons=['MARKET_CALENDAR_CLOSING'])
        fill = (quote["ask"] if sign == 1 else quote["bid"]) + sign * self._slippage
        try:
            executable = Candidate(
                original.side,
                fill,
                original.stop,
                original.target,
                original.expires_at,
                original.evidence,
            )
        except ValueError:
            return dict(approved=False, reasons=["PRICE_MOVED_OUTSIDE_FROZEN_LEVELS"])
        equity = self.equity(quote)
        assessment = assess_candidate(
            executable,
            quality=DataQuality(True),
            session=setup["snapshot"]["session"][0],
            allowed_sessions=frozenset(active_sessions),
            spread_pips=(quote["ask"] - quote["bid"]) / self._price_unit,
            pip_size=self._price_unit,
            max_slippage_price=self._slippage,
            value_per_price_unit=1,
            commission_per_unit=2 * self._fee_per_value_unit,
            account=AccountSnapshot(
                equity,
                self.data["peak"],
                self.data["day_start"],
                self.data["daily_entries"],
            ),
            limits=self._limits,
            now=utc(quote.get("observed_at", quote["at"])),
            entry_is_executable=True,
            fixed_units=self.data["units"],
        )
        if not assessment.approved:
            return dict(approved=False, reasons=list(assessment.reasons))
        decision_id = fingerprint(
            dict(
                session=self.data["session_id"],
                signal=setup["signal_at"],
                side=original.side,
            )
        )
        self.data["position"] = dict(
            decision_id=decision_id,
            side=original.side,
            sign=sign,
            lot=self.data["lot"],
            units=self.data["units"],
            entry=fill,
            entry_at=quote.get("observed_at", quote["at"]),
            stop=original.stop,
            target=original.target,
            initial_risk=assessment.risk_budget,
            probability=probability,
            features=features,
            coverage_uncertain=False,
            hypothesis=copy.deepcopy(hypothesis),
        )
        self.data["daily_entries"] += 1
        self.event(
            "opened",
            quote.get("observed_at", quote["at"]),
            decision_id=decision_id,
            position=copy.deepcopy(self.data["position"]),
            signal_at=setup["signal_at"],
            risk_reward=assessment.risk_reward,
        )
        return dict(approved=True, position=self.data["position"])

    def summary(self):
        quote = self.data["last_quote"]
        equity = self.equity(quote) if quote else self.data["balance"]
        return dict(
            balance=self.data["balance"],
            equity=equity,
            realized_pnl=self.data["balance"] - PROTOCOL["initial_equity"],
            realized_today=self.data["realized_today"],
            unrealized_pnl=equity - self.data["balance"],
            closed_trades=self.data["closed_trades"],
            wins=self.data["wins"],
            losses=self.data["losses"],
            uncertain_trades=self.data["uncertain_trades"],
            currency="USD",
            mode="paper",
            research_mode=self.data["research_mode"],
        )
