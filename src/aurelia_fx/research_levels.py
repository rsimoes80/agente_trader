"""Equivalent level calculations with bounded caching, for offline replay only."""
from dataclasses import replace
from datetime import datetime,timedelta

from .levels import SupportResistanceEngine
from .trend import timeframe_seconds


class ResearchLevels(SupportResistanceEngine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache={}

    def evaluate(self,histories,*,symbol,now):
        output=[]
        for tf,bars in histories.items():
            seconds=timeframe_seconds(tf)
            if bars and bars[-1].timestamp+timedelta(seconds=seconds)>now:
                raise ValueError('Levels cannot use future or unfinished candles.')
            key=(symbol,tuple(bars))
            previous=self.cache.get(tf)
            if previous is None or previous[0]!=key:
                levels=super().evaluate({tf:bars},symbol=symbol,now=now)
                self.cache[tf]=(key,levels)
            else:levels=previous[1]
            for level in levels:
                expired=(now-datetime.fromisoformat(level.created_at_utc)).total_seconds()>self.ttl_bars*seconds
                status='expired' if expired else 'active'
                output.append(level if status==level.status else replace(level,status=status))
        return tuple(output)

    @staticmethod
    def context(levels,price,*,target=None,side=None,limit=None):
        # Original ranking depends only on geometry and IDs. Serialize after selecting.
        def distance(level):return max(level.lower_bound-price,price-level.upper_bound,0.)
        ranked=sorted((v for v in levels if v.status=='active'),
                      key=lambda v:(distance(v),v.timeframe,v.level_id))
        selected=ranked if limit is None else ranked[:limit]
        if limit is not None:
            for role,above in (('resistance',True),('support',False)):
                nearest=next((v for v in ranked if v.role==role and
                              (v.lower_bound>price if above else v.upper_bound<price)),None)
                if nearest and nearest not in selected:selected.append(nearest)
        return tuple(dict(v.as_dict(),distance=distance(v),interferes_with_target=bool(
            target is not None and ((side=='long' and v.role=='resistance' and price<v.lower_bound<target)
            or (side=='short' and v.role=='support' and target<v.upper_bound<price)))) for v in selected)
