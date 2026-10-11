from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    The user model of this project.

    Django recommends a custom user model for every new project, even if the
    default one suffices: it can be extended later on, whereas switching
    `AUTH_USER_MODEL` after the first migration is very laborious. See
    https://docs.djangoproject.com/en/6.1/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project
    """
