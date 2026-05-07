"""SavedAddress model — at-most-one default per user invariant."""
import pytest

from apps.accounts.models import SavedAddress


@pytest.mark.integration
class TestSavedAddress:
    def test_create_saved_address(self, db, client_user):
        addr = SavedAddress.objects.create(
            user=client_user, label="Home",
            address="123 Main St, Irvine, CA",
            is_default=True,
        )
        assert addr.id is not None
        assert addr.is_default is True

    def test_setting_a_new_default_unsets_the_previous(self, db, client_user):
        first = SavedAddress.objects.create(
            user=client_user, label="Home",
            address="123 Main St", is_default=True,
        )
        second = SavedAddress.objects.create(
            user=client_user, label="Work",
            address="456 Spectrum Dr", is_default=True,
        )
        first.refresh_from_db()
        assert first.is_default is False
        assert second.is_default is True

    def test_two_users_can_each_have_their_own_default(self, db, client_user):
        from tests.factories import ClientUserFactory
        other = ClientUserFactory()
        SavedAddress.objects.create(user=client_user, label="Home", address="A", is_default=True)
        SavedAddress.objects.create(user=other,        label="Home", address="B", is_default=True)
        # No constraint violation — partial unique index scopes per user

    def test_user_can_have_many_non_default_addresses(self, db, client_user):
        SavedAddress.objects.create(user=client_user, label="Home", address="A")
        SavedAddress.objects.create(user=client_user, label="Work", address="B")
        SavedAddress.objects.create(user=client_user, label="Parents", address="C")
        assert SavedAddress.objects.filter(user=client_user).count() == 3
        assert SavedAddress.objects.filter(user=client_user, is_default=True).count() == 0
