"""Contextual selection of explicit paper hypotheses, without human promotion.

Rewards describe observed simulations. Scores are not calibrated probabilities
and do not authorize broker orders or prove that a strategy is profitable.
"""

import copy
import json
import math
from datetime import timedelta

from .agent_model import fingerprint
from .agent_strategy import SPEC_HASH
from .agent_strategy import strategy_hash
from .historical.core import utc
from .entry_trend import entry_blocker, POLICY_ID
from .regime import MarketRegimeEngine

REGIME_HASH = MarketRegimeEngine().config_hash

HYPOTHESES = (
    ("context_pullback", "Pullback com direção H1"),
    ("forecast_pullback", "Pullback confirmado pelo Timestral"),
    ("price_action_pullback", "Gatilho de price action"),
)
SPEC = dict(version="autonomous-context-v1", strategy_spec=SPEC_HASH,
            hypotheses=list(HYPOTHESES), selection="contextual_ucb_with_shrunk_historical_prior",
            prior_max_weight=5, exploration=0.6, reward_clip_r=2,
            loss_policy="prefer_another_eligible_hypothesis_next_time",
            scope="contextual_experiments", native_execution="demo_only_via_gateway")


def context_key(features, snapshot, *, profile=None):
    sessions = "+".join(sorted(snapshot.get("session") or ["outside"]))
    key=f"{POLICY_ID}|{snapshot.get('regime_config_hash','unversioned')}|{snapshot.get('regime','UNKNOWN')}|H1:{int(features['h1_direction_known'])}|{sessions}"
    return profile.learning_namespace+'|'+key if profile else key


def eligible(features):
    choices = ["price_action_pullback"]
    if features["h1_direction_known"]:
        choices.append("context_pullback")
    if features["forecast_3_atr"] > 0 and features["forecast_6_atr"] > 0:
        choices.append("forecast_pullback")
    return choices


def empty_stats():
    return dict(n=0,wins=0,losses=0,flat=0,sum_r=0.0,net_pnl=0.0)


def add_reward(stats, pnl, result_r):
    if not math.isfinite(pnl) or not math.isfinite(result_r):
        raise ValueError("Resultado de pesquisa inválido.")
    stats["n"] += 1
    stats["wins"] += int(pnl>0)
    stats["losses"] += int(pnl<0)
    stats["flat"] += int(pnl==0)
    stats["sum_r"] += max(-2,min(2,result_r))
    stats["net_pnl"] += pnl


def learn(state, position, pnl, result_r):
    """Called inside the same account update/commit as the observed close."""
    hypothesis = position.get("hypothesis")
    if not hypothesis:
        return
    if hypothesis.get('symbol','EURUSD')!=state.get('symbol','EURUSD') or hypothesis.get('profile_id')!=state.get('profile_id'):
        raise ValueError('HYPOTHESIS_RESULT_INSTRUMENT_MISMATCH')
    if position["coverage_uncertain"]:
        state["excluded_uncertain"] = state.get("excluded_uncertain",0)+1
        return
    from .continual_learning import real_result
    real_result(state,hypothesis,pnl,result_r)
    if hypothesis.get('learning_version'):
        return  # Versioned variants have their own contexts; do not relabel them as legacy arms.
    key, arm = hypothesis["context"], hypothesis["id"]
    cell = state.setdefault("live",{}).setdefault(key,{})
    add_reward(cell.setdefault(arm,empty_stats()),pnl,result_r)
    state["last_result"] = dict(hypothesis=arm,context=key,net_pnl=pnl,result_in_r=result_r)
    if pnl <= 0:
        state.setdefault("last_failed",{})[key] = arm
    else:
        state.setdefault("last_failed",{}).pop(key,None)


class AutonomousLab:
    def __init__(self, configuration, execution_mode="paper", *, profile=None):
        if execution_mode not in {"paper","demo"}:raise ValueError("Modo de execução não permitido.")
        self.execution_mode=execution_mode
        self.profile=profile
        identity=dict(spec=SPEC,configuration=configuration,execution_mode=execution_mode)
        if profile:identity['instrument']=profile.learning_namespace
        self.protocol_id = fingerprint(identity)

    def select(self, features, snapshot, state):
        if snapshot.get('symbol','EURUSD')!=(self.profile.symbol if self.profile else 'EURUSD') or snapshot.get('profile_id')!=(self.profile.fingerprint if self.profile else None):
            raise ValueError('HYPOTHESIS_SELECTION_INSTRUMENT_MISMATCH')
        if self.profile and (state.get('symbol')!=self.profile.symbol or state.get('profile_id')!=self.profile.fingerprint):
            raise ValueError('HYPOTHESIS_MEMORY_INSTRUMENT_MISMATCH')
        side = {1: "long", -1: "short"}.get(features.get("side"), "invalid")
        blocker = entry_blocker(snapshot, side)
        if blocker:
            raise ValueError(blocker)
        key = context_key(features,snapshot,profile=self.profile)
        arms = eligible(features)
        previous_failure = state.get("last_failed",{}).get(key)
        alternatives = [arm for arm in arms if arm != previous_failure]
        if alternatives:
            arms = alternatives
        live = state.get("live",{}).get(key,{})
        history = state.get("history",{}).get(key,{})
        total = sum(value["n"] for value in live.values())
        def score(arm):
            current = live.get(arm,empty_stats())
            prior = history.get(arm,empty_stats())
            weight = min(5,prior["n"])
            prior_mean = prior["sum_r"]/prior["n"] if prior["n"] else 0
            mean = (current["sum_r"]+weight*prior_mean)/(5+current["n"]+weight)
            exploration = 0.6*math.sqrt(math.log(total+2)/(current["n"]+1))
            return mean+exploration
        chosen = max(sorted(arms),key=score)
        return dict(id=chosen,name=dict(HYPOTHESES)[chosen],context=key,
                    **(dict(symbol=self.profile.symbol,profile_id=self.profile.fingerprint) if self.profile else {}),
                    protocol_id=self.protocol_id,entry_policy=POLICY_ID,selection_score=score(chosen),
                    reason="Alternativa após resultado não positivo." if previous_failure
                    else "Hipótese selecionada pelo histórico deste contexto e pela exploração.")

    def summary(self, state):
        from .continual_learning import summary as learning_summary
        rows=[]
        prefix=(self.profile.learning_namespace+'|' if self.profile else '')+POLICY_ID+'|'+REGIME_HASH+'|'
        for arm,name in HYPOTHESES:
            aggregate=empty_stats()
            for key,cell in state.get("live",{}).items():
                if not key.startswith(prefix):
                    continue
                stats=cell.get(arm,empty_stats())
                for key in aggregate:aggregate[key]+=stats[key]
            rows.append(dict(id=arm,name=name,**aggregate))
        return dict(protocol_id=state.get("protocol_id",self.protocol_id),mode="autonomous_demo_research" if self.execution_mode=="demo" else "autonomous_paper_research",
                    entry_policy=POLICY_ID,
                    regime_config_hash=REGIME_HASH,
                    hypotheses=rows,historical_samples=state.get("historical_samples",0),
                    last_result=state.get("last_result") if (state.get('last_result') or {}).get('context','').startswith(prefix) else None,
                    previous_policy_results=sum(v.get('n',0) for key,cell in state.get('live',{}).items()
                                                if not key.startswith(prefix) for v in cell.values()),
                    excluded_uncertain=state.get("excluded_uncertain",0),
                    native_orders=self.execution_mode=="demo",continual=learning_summary(state))

    def seed(self, memory, *, clock_id, configuration, as_of):
        """Reuse only development labels; former validation/final are excluded."""
        profile=self.profile
        def record_type(kind):return profile.record_type(kind) if profile else kind
        def fresh():
            return dict(protocol_id=self.protocol_id,entry_policy=POLICY_ID,regime_config_hash=REGIME_HASH,
                        live={},history={},historical_samples=0,seed_complete=True,
                        **(dict(symbol=profile.symbol,profile_id=profile.fingerprint) if profile else {}))
        with memory.pool.connection() as c:
            rows=c.execute("""SELECT payload_json,payload_sha256 FROM project_records
                WHERE record_type=%s ORDER BY recorded_at DESC LIMIT 20""",(record_type('agent_training_dataset'),)).fetchall()
            compatible=[]
            for row in rows:
                data=json.loads(row["payload_json"]); manifest=data["manifest"]
                if profile and memory._encode(data)[1]!=row['payload_sha256']:
                    raise ValueError('SEED_DATASET_INTEGRITY_ERROR')
                if (manifest.get('symbol','EURUSD')==(profile.symbol if profile else 'EURUSD')
                    and manifest.get('profile_id')==(profile.fingerprint if profile else None)
                    and manifest["clock_id"]==clock_id
                    and manifest["model_configuration"]==configuration
                    and fingerprint(manifest["strategy"])==strategy_hash(profile)
                    and as_of-timedelta(days=7)<=utc(manifest["as_of"])<=as_of):
                    compatible.append(data)
            if not compatible:
                return fresh()
            selected=max(compatible,key=lambda d:(d["manifest"]["training_days"],d["manifest"]["as_of"]))
            samples=c.execute("""SELECT payload_json,payload_sha256 FROM project_records
                WHERE record_type=%s AND record_key=ANY(%s)""",
                (record_type('agent_training_sample'),selected["sample_ids"])).fetchall()
        state={**fresh(),'seed_run_id':selected['run_id'],'seed_scope':'development_only_overlapping_counterfactuals'}
        boundary=utc(selected["manifest"]["boundaries"][0])
        seen=set()
        for row in samples:
            sample=json.loads(row["payload_json"])
            if profile and memory._encode(sample)[1]!=row['payload_sha256']:
                raise ValueError('SEED_SAMPLE_INTEGRITY_ERROR')
            if sample.get('symbol','EURUSD')!=(profile.symbol if profile else 'EURUSD') or sample.get('profile_id')!=(profile.fingerprint if profile else None):
                raise ValueError('SEED_SAMPLE_INSTRUMENT_MISMATCH')
            if profile and (sample.get('spec_hash')!=strategy_hash(profile) or sample.get('snapshot',{}).get('symbol')!=profile.symbol or sample.get('snapshot',{}).get('profile_id')!=profile.fingerprint):
                raise ValueError('SEED_SAMPLE_PROFILE_MISMATCH')
            if sample["sample_id"] in seen or utc(sample["exit_at"])>=boundary:
                continue
            seen.add(sample["sample_id"])
            side={1:'long',-1:'short'}.get(sample['features'].get('side'),'invalid')
            if (sample.get('snapshot',{}).get('regime_config_hash') != REGIME_HASH
                or entry_blocker(sample.get('snapshot'),side)):
                continue
            key=context_key(sample["features"],sample["snapshot"],profile=profile)
            cell=state["history"].setdefault(key,{})
            for arm in eligible(sample["features"]):
                add_reward(cell.setdefault(arm,empty_stats()),sample["net_pnl"],sample["result_in_r"])
            state["historical_samples"]+=1
        return copy.deepcopy(state)
