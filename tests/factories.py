"""Factory-boy factories — shared test data builders."""
import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import User


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@butler.test")
    full_name = factory.Faker("name")
    role = "client"
    status = "active"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "TestPass123!")
        user = model_class.objects.create_user(password=password, **kwargs)
        return user


class ClientUserFactory(UserFactory):
    role = "client"


class OperatorUserFactory(UserFactory):
    role = "operator"


class DriverUserFactory(UserFactory):
    role = "driver"


class AdminUserFactory(UserFactory):
    role = "admin"
    is_staff = True
    is_superuser = True
