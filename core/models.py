from django.db import models
from django.conf import settings

class GlobalSettings(models.Model):
    """
    Model to store global settings for the application.
    """
    survey_cooldown_days = models.PositiveIntegerField(
        default=60,
        help_text="Number of days a survey will be disabled after completion"
    )
    
    class Meta:
        verbose_name_plural = "Global Settings"
    
    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def load(cls):
        """
        Load the global settings, creating default if they don't exist.
        """
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
