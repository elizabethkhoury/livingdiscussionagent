from src.learn.trainer import LearningTrainer


class LearningWorker:
    def __init__(self):
        self.trainer = LearningTrainer()

    def run_once(self):
        return self.trainer.update()
