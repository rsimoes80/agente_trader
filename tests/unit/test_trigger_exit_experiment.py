import copy
from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.correction_experiment import replay as original_replay
from aurelia_fx.trigger_exit_experiment import ARMS,accepts,feature_rows,replay


class TriggerExitExperimentTests(unittest.TestCase):
    def fixture(self):
        start=datetime(2026,1,5,13,tzinfo=timezone.utc)
        tr=dict(direction='bullish',state='BULL_CONFIRMED',timestamp_utc=start.isoformat())
        sample=dict(sample_id='fixture',signal_at=start.isoformat(),entry_at=start.isoformat(),
            arms=['strict_or_guarded_correction'],snapshot=dict(snapshot_id='fixture',session=['london'],regime='UNKNOWN',
                macro_trend=copy.deepcopy(tr),context_trend=tr),
            candidate=dict(side='long',entry=1.1,stop=1.098,target=1.105,
                           expires_at=(start+timedelta(minutes=5)).isoformat(),evidence=[]))
        bars=[Candle(start+timedelta(minutes=5*i),1.1,1.101,1.0995,1.1005,100,1) for i in range(28)]
        features={'fixture':dict(body_atr=.6,directional_close_location=.8,break_previous3=True)}
        return start,sample,bars,features

    def test_filters_change_only_one_condition_and_holding_is_separate(self):
        f=dict(body_atr=.49,directional_close_location=.74,break_previous3=False)
        for arm in ('reference','holding_30min','holding_120min'):self.assertTrue(accepts(f,arm))
        for arm in ('body_05atr','close_75pct','break_previous3'):self.assertFalse(accepts(f,arm))
        for key,arm,value in [('body_atr','body_05atr',.5),('directional_close_location','close_75pct',.75),('break_previous3','break_previous3',True)]:
            x=copy.deepcopy(f);x[key]=value
            self.assertTrue(accepts(x,arm))
            self.assertEqual(ARMS[arm]['holding_bars'],12)
        with self.assertRaises(ValueError):accepts(f,'unknown')

    def test_duration_variants_preserve_candidate_and_risk(self):
        start,s,bars,f=self.fixture();original=copy.deepcopy(s)
        for arm,count in [('holding_30min',6),('reference',12),('holding_120min',24)]:
            r=replay([s],bars,f,arm=arm,start=start,end=start+timedelta(hours=3),units=1000)
            self.assertEqual(r['closed_trades'],1)
            self.assertEqual(r['trades'][0]['bars_held'],count)
            self.assertEqual(r['exit_reasons'],{'TIME_EXPIRY':1})
            self.assertGreater(r['commission_closed'],0)
            self.assertFalse(r['unresolved_position'])
        self.assertEqual(s,original)

    def test_reference_exactly_matches_existing_portfolio(self):
        start,s,bars,f=self.fixture();args=dict(start=start,end=start+timedelta(hours=3),units=1000)
        old=original_replay([s],bars,arm='strict_or_guarded_correction',**args)
        current=replay([s],bars,f,arm='reference',**args)
        for key in ('net_pnl','closed_trades','wins','losses','gross_pnl_closed','spread_cost_closed','commission_closed','slippage_cost_closed'):
            self.assertEqual(old[key],current[key])

    def test_features_never_use_future_and_reject_wrong_side_or_future_trend(self):
        start,s,_,_=self.fixture()
        history=[Candle(start-timedelta(minutes=5*i),1.1,1.101,1.099,1.1,100,1) for i in range(20,0,-1)]
        current=feature_rows([s],history)
        future=history+[Candle(start,2,3,1.5,2.5,100,1)]
        self.assertEqual(current,feature_rows([s],future))
        bad=copy.deepcopy(s);bad['candidate']['side']='short'
        with self.assertRaises(ValueError):feature_rows([bad],history)
        bad=copy.deepcopy(s);bad['snapshot']['macro_trend']['timestamp_utc']=(start+timedelta(hours=1)).isoformat()
        with self.assertRaises(ValueError):feature_rows([bad],history)


if __name__=='__main__':unittest.main()
