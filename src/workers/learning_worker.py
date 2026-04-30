from src.learn.diary_builder import DiaryBuilder
from src.learn.trainer import LearningTrainer


class LearningWorker:
    def __init__(self):
        self.trainer = LearningTrainer()
        self.diary_builder = DiaryBuilder()

    def run_once(self):
        learning_report = self.trainer.update()
        diary_report = self.diary_builder.update()
        return {
            "learning": learning_report.model_dump(),
            "diary": diary_report,
        }
