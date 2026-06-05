from src.learn.diary_builder import DiaryBuilder
from src.learn.trainer import LearningTrainer
from src.learn.voice_sampler import VoiceSampler
from src.runtime.halt_guard import operation_blocked_result


class LearningWorker:
    def __init__(self):
        self.trainer = LearningTrainer()
        self.diary_builder = DiaryBuilder()
        self.voice_sampler = VoiceSampler()

    def run_once(self):
        blocked = operation_blocked_result("learn-once")
        if blocked is not None:
            return blocked
        learning_report = self.trainer.update()
        diary_report = self.diary_builder.update()
        new_voice_samples = self.voice_sampler.update()
        return {
            "learning": learning_report.model_dump(),
            "diary": diary_report,
            "voice_samples_added": new_voice_samples,
            "voice_samples_total": self.voice_sampler.count(),
        }
