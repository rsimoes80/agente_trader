import os
import unittest


@unittest.skipUnless(os.environ.get('AURELIA_TEST_TRAINING')=='1','Isolated training environment opt-in')
class TrainingLossTests(unittest.TestCase):
    def test_loss_is_differentiable_and_uses_all_quantiles(self):
        import torch
        from aurelia_fx.training.proof import pinball_loss
        prediction=torch.tensor([[[.8,1.,1.2]]],requires_grad=True)
        target=torch.tensor([[1.1]])
        loss=pinball_loss(prediction,target,[.1,.5,.9])
        self.assertAlmostEqual(loss.item(),.03,places=6)
        loss.backward()
        self.assertTrue(torch.isfinite(prediction.grad).all())
        self.assertTrue((prediction.grad!=0).all())

    def test_perfect_predictions_have_zero_loss(self):
        import torch
        from aurelia_fx.training.proof import pinball_loss
        self.assertEqual(pinball_loss(torch.ones(1,2,3),torch.ones(1,2),[.1,.5,.9]).item(),0)

    def test_invalid_quantile_shapes_rejected(self):
        import torch
        from aurelia_fx.training.proof import pinball_loss
        with self.assertRaises(ValueError):pinball_loss(torch.ones(1,2,3),torch.ones(1,3),[.1,.5,.9])
