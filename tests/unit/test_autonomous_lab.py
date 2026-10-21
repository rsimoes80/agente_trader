import unittest
from aurelia_fx.autonomous_lab import AutonomousLab
from aurelia_fx.agent_paper import PaperAccount
from . import test_agent_paper as paper_fixtures


class AutonomousLabTests(unittest.TestCase):
    def setUp(self):
        self.fixture=paper_fixtures.PaperAccountTests();self.fixture.setUp()
        self.lab=AutonomousLab("fixture-config")
        self.features=dict(h1_direction_known=0,forecast_3_atr=0.1,forecast_6_atr=0.2)
        self.snapshot=dict(regime="UNKNOWN",session=["london"])
        self.fixture.setup["production_eligible"]=False
        self.account=PaperAccount("research","0.01",self.fixture.contract,self.lab.protocol_id,"clock",research_mode=True)

    def open(self):
        hypothesis=self.lab.select(self.features,self.snapshot,self.account.data["lab_state"])
        result=self.account.open(self.fixture.setup,self.features,None,self.fixture.quote(3),
                                 active_sessions=("london",),hypothesis=hypothesis)
        self.assertTrue(result["approved"])
        return hypothesis

    def test_experiment_is_explicit_and_loss_selects_another_eligible_hypothesis(self):
        first=self.open()
        self.account.mark(self.fixture.quote(8,bid=1.0979,ask=1.098))
        state=self.account.data["lab_state"]
        self.assertLess(state["last_result"]["net_pnl"],0)
        following=self.lab.select(self.features,self.snapshot,state)
        self.assertNotEqual(first["id"],following["id"])
        self.assertEqual(sum(row["losses"] for row in self.lab.summary(state)["hypotheses"]),1)
        # Experimental authority never turns the validated executor's gate off.
        self.assertFalse(self.fixture.account.open(self.fixture.setup,self.features,None,self.fixture.quote(3),active_sessions=("london",))["approved"])

    def test_gain_updates_research_memory_and_survives_restart_and_new_session(self):
        self.open();self.account.mark(self.fixture.quote(8,bid=1.1051,ask=1.1052))
        restored=PaperAccount("research","0.01",self.fixture.contract,self.lab.protocol_id,"clock",
                              checkpoint=self.account.snapshot(),research_mode=True)
        next_session=PaperAccount("next","0.01",self.fixture.contract,self.lab.protocol_id,"clock",
                                 previous_account=restored.snapshot(),research_mode=True)
        self.assertEqual(sum(row["wins"] for row in self.lab.summary(next_session.data["lab_state"])["hypotheses"]),1)
        self.assertAlmostEqual(next_session.data["balance"],10004.89)

    def test_quote_gap_is_not_treated_as_reliable_learning_reward(self):
        self.open();self.account.mark(self.fixture.quote(100,bid=1.1051,ask=1.1052))
        state=self.account.data["lab_state"]
        self.assertEqual(state["excluded_uncertain"],1)
        self.assertEqual(sum(row["n"] for row in self.lab.summary(state)["hypotheses"]),0)
        self.assertEqual(self.account.data["closed_trades"],1)

    def test_no_historical_prior_or_h1_direction_does_not_stop_research(self):
        state={}
        features={**self.features,"forecast_3_atr":-1}
        result=self.lab.select(features,self.snapshot,state)
        self.assertEqual(result["id"],"price_action_pullback")
        self.assertNotIn("probability",result)
