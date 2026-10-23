import copy
from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.context_experiment import ARMS,context_for,passes
from aurelia_fx.domain import Candle


class ContextExperimentTests(unittest.TestCase):
    def fixture(self,bearish=False):
        signal=datetime(2026,1,7,12,tzinfo=timezone.utc)
        prices=[1.1]*20+[1.1005,1.101,1.1015,1.102,1.1025,1.103,1.1028,1.1026,1.1024,1.104]
        def bar(at,op,cl):
            hi=max(op,cl)+.0001;lo=min(op,cl)-.0001
            if bearish:op,cl,hi,lo=2.25-op,2.25-cl,2.25-lo,2.25-hi
            return Candle(at,op,hi,lo,cl,100,1)
        m5=[bar(signal-timedelta(minutes=5*(30-i)),prices[i-1] if i else prices[i],p) for i,p in enumerate(prices)]
        h1=[]
        for i in range(30):
            op=1.1 if i<27 else 1.1+(i-26)*.001
            cl=1.1 if i<26 else 1.1+min(i-25,3)*.001
            h1.append(bar(signal-timedelta(hours=30-i),op,cl))
        tr=dict(direction='bearish' if bearish else 'bullish',state='BEAR_CONFIRMED' if bearish else 'BULL_CONFIRMED',timestamp_utc=signal.isoformat())
        tr['last_confirmed_high' if bearish else 'last_confirmed_low']=dict(price=1.151 if bearish else 1.099,confirmed_at=(signal-timedelta(hours=10)).isoformat())
        sample=dict(sample_id='fixture',signal_at=signal.isoformat(),entry_at=signal.isoformat(),
            snapshot=dict(regime='UNKNOWN',macro_trend=copy.deepcopy(tr),context_trend=tr),
            candidate=dict(side='short' if bearish else 'long',entry=m5[-1].close,
                stop=1.149 if bearish else 1.101,target=1.1385 if bearish else 1.1115))
        return sample,m5,h1

    def test_preceding_impulse_and_shallow_correction_both_directions(self):
        for bearish in (False,True):
            sample,m5,h1=self.fixture(bearish);f=context_for(sample,m5,h1)
            self.assertTrue(passes(f,'prior_h1_impulse'))
            self.assertTrue(passes(f,'m5_impulse_shallow_correction'))
            self.assertLessEqual(datetime.fromisoformat(f['h1_prior_leg_end']),datetime.fromisoformat(f['correction_start']))
            self.assertLessEqual(datetime.fromisoformat(f['m5_prior_leg_end']),datetime.fromisoformat(f['correction_start']))

    def test_h1_containing_correction_cannot_establish_the_previous_impulse(self):
        sample,m5,h1=self.fixture();before=context_for(sample,m5,h1)
        last=h1[-1];h1[-1]=Candle(last.timestamp,1.1,2,1,1.9,100,1)
        after=context_for(sample,m5,h1)
        self.assertEqual(before['h1_impulse_atr'],after['h1_impulse_atr'])
        self.assertEqual(before['h1_efficiency'],after['h1_efficiency'])

    def test_future_h1_and_countertrend_are_rejected(self):
        sample,m5,h1=self.fixture()
        future=Candle(m5[-1].timestamp+timedelta(minutes=5),1.1,1.11,1.09,1.1,100,1)
        with self.assertRaises(ValueError):context_for(sample,m5,h1+[future])
        bad=copy.deepcopy(sample);bad['snapshot']['macro_trend'].update(direction='bearish',state='BEAR_CONFIRMED')
        with self.assertRaises(ValueError):context_for(bad,m5,h1)

    def test_filters_are_isolated_and_unknown_room_never_means_free_space(self):
        sample,m5,h1=self.fixture();f=context_for(sample,m5,h1)
        self.assertTrue(passes(f,'reference'))
        self.assertFalse(passes(f,'known_h1_room_to_target'))
        f['h1_room_r']=2.5;f['target_r']=2.5
        self.assertTrue(passes(f,'known_h1_room_to_target'))
        f['h1_impulse_atr']=-1
        self.assertFalse(passes(f,'prior_h1_impulse'))
        self.assertTrue(passes(f,'m5_impulse_shallow_correction'))
        self.assertTrue(passes(f,'known_h1_room_to_target'))
        f['m5_retracement']=1.1
        self.assertFalse(passes(f,'m5_impulse_shallow_correction'))
        self.assertEqual(len(ARMS),4)
        with self.assertRaises(ValueError):passes(f,'unknown')

    def test_pivot_review_leg_ends_before_first_correction_bar(self):
        from math import sin
        from run_context_review import leg
        start=datetime(2026,1,7,9,tzinfo=timezone.utc)
        bars=[]
        for i in range(40):
            close=1.1+.001*sin(i)
            bars.append(Candle(start+timedelta(minutes=5*i),close,close+.0001,close-.0001,close,100,1))
        signal=bars[-1].timestamp+timedelta(minutes=5);correction=bars[-4].timestamp
        result=leg(bars,'short',signal,correction,300,max(b.high for b in bars[-4:-1]))
        self.assertIsNotNone(result)
        self.assertLessEqual(datetime.fromisoformat(result['end'])+timedelta(minutes=5),correction)
        self.assertLessEqual(datetime.fromisoformat(result['end_confirmed']),signal)


if __name__=='__main__':unittest.main()
