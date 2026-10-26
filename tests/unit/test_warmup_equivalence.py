"""Priming can skip reports, but must preserve every state and next snapshot."""
from datetime import datetime,timedelta,timezone
import itertools
import math
import unittest
from unittest.mock import patch

from aurelia_fx.agent_research import intelligence_session


class WarmupEquivalenceTests(unittest.TestCase):
    def bars(self):
        start=datetime(2026,10,5,0,tzinfo=timezone.utc)
        rows=[]
        for i in range(650):
            if 360<=i<363:continue  # Real missing exposure bars must reset both paths.
            price=1.1+.0001*math.sin(i*.2)+.000001*i
            rows.append(dict(timestamp=(start+timedelta(minutes=5*i)).isoformat(),open=price,
                high=price+.0002,low=price-.0002,close=price+.00005*math.cos(i),volume=100+i%9,spread_pips=1.1))
        return rows

    def run_path(self, rows, *, fast):
        session=intelligence_session();observed=[];ids=itertools.count()
        with patch('aurelia_fx.observer.uuid4',side_effect=lambda:'observation-'+str(next(ids))):
            for i,row in enumerate(rows):
                now=datetime.fromisoformat(row['timestamp'])+timedelta(minutes=5)
                snapshot=session.update([row],spread_pips=row['spread_pips'],observed_at=now,
                    warmup_only=fast and i<len(rows)-41)
                if i>=len(rows)-41:observed.append(snapshot.as_dict())
        return session,observed

    def test_final_and_next_40_snapshots_are_identical(self):
        rows=self.bars();normal,snapshots=self.run_path(rows,fast=False);fast,primed=self.run_path(rows,fast=True)
        self.assertEqual(snapshots,primed)
        self.assertEqual(normal.aggregator.history,fast.aggregator.history)
        self.assertEqual(normal.observer.trends.counts,fast.observer.trends.counts)
        self.assertEqual(normal.observer.regimes._tracks,fast.observer.regimes._tracks)

    def test_priming_returns_no_actionable_snapshot(self):
        s=intelligence_session();row=self.bars()[0]
        result=s.update([row],spread_pips=1.1,observed_at=datetime.fromisoformat(row['timestamp'])+timedelta(minutes=5),warmup_only=True)
        self.assertIsNone(result)
        self.assertIsNone(s.snapshot)
        self.assertIsNotNone(s.last)
