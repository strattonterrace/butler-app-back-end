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


class TerritoryFactory(DjangoModelFactory):
    class Meta:
        model = "territories.Territory"

    name = factory.Sequence(lambda n: f"Territory {n}")


class DriverProfileFactory(DjangoModelFactory):
    class Meta:
        model = "drivers.DriverProfile"

    user = factory.SubFactory(DriverUserFactory)
    vehicle_make = "Toyota"
    vehicle_model = "Camry"
    vehicle_year = 2022
    license_plate = factory.Sequence(lambda n: f"BTLR{n:03d}")
    approval_status = "approved"
    territory = factory.SubFactory(TerritoryFactory)


class ServiceRequestFactory(DjangoModelFactory):
    class Meta:
        model = "service_requests.ServiceRequest"

    client = factory.SubFactory(ClientUserFactory)
    service_type = "grocery"
    title = factory.Sequence(lambda n: f"Errand #{n}")
    description = "Test errand description"
    pickup_location = "Trader Joe's, Newport Beach"
    dropoff_location = "123 Main St, Irvine, CA 92618"
    urgency = "asap"
    status = "submitted"
