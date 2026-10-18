"""Branded email notifications (M3) — content, routing, and HTML/text parts."""
import pytest

from apps.notifications import services as notifications
from tests.factories import (
    AdminUserFactory,
    ClientUserFactory,
    DriverProfileFactory,
    DriverUserFactory,
    OperatorUserFactory,
    ServiceRequestFactory,
    TerritoryFactory,
)

pytestmark = pytest.mark.django_db


def _html(message):
    """The text/html alternative attached to a sent message."""
    assert message.alternatives, "email has no HTML alternative"
    content, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    return content


class TestAccountEmails:
    def test_welcome(self, mailoutbox):
        user = ClientUserFactory(full_name="Jane Smith", email="jane@example.com")
        notifications.send_welcome_email(user)

        assert len(mailoutbox) == 1
        msg = mailoutbox[0]
        assert msg.to == ["jane@example.com"]
        assert msg.subject == "Welcome to Butler"
        html = _html(msg)
        assert "Butler" in html
        assert "/subscribe" in html          # CTA link
        assert "Hi Jane," in html            # personalized intro
        assert "Hi Jane," in msg.body        # plain-text part too

    def test_password_reset(self, mailoutbox):
        user = ClientUserFactory(full_name="Sam Lee", email="sam@example.com")
        notifications.send_password_reset_email(user, "https://app.mybutlerclub.com/reset?x=1")

        assert len(mailoutbox) == 1
        assert mailoutbox[0].subject == "Reset your Butler password"
        assert "https://app.mybutlerclub.com/reset?x=1" in _html(mailoutbox[0])

    def test_plain_text_is_not_html_escaped(self, mailoutbox):
        # Apostrophes must stay literal in the text part (regression guard).
        user = ClientUserFactory(full_name="O'Brien Test", email="o@example.com")
        notifications.send_welcome_email(user)
        assert "&#x27;" not in mailoutbox[0].body
        assert "Hi O'Brien," in mailoutbox[0].body


class TestRequestEmails:
    def test_new_request_goes_to_territory_operator(self, mailoutbox):
        terr = TerritoryFactory()
        operator = OperatorUserFactory(territory=terr, email="op@example.com")
        OperatorUserFactory()  # different territory — should NOT receive
        client = ClientUserFactory(territory=terr)
        sr = ServiceRequestFactory(client=client, title="Groceries", status="submitted")

        notifications.send_new_request_email(sr)

        assert len(mailoutbox) == 1
        msg = mailoutbox[0]
        assert msg.to == ["op@example.com"]
        assert "Groceries" in msg.subject
        assert "Newport Beach" in _html(msg)      # info row rendered (HTML escapes the apostrophe)

    def test_assigned_emails_client_and_driver_with_role_links(self, mailoutbox):
        driver = DriverUserFactory(email="driver@example.com")
        client = ClientUserFactory(email="client@example.com")
        sr = ServiceRequestFactory(client=client, driver=driver, status="assigned", title="Dinner")

        notifications.send_status_update_email(sr, old_status="reviewed")

        assert len(mailoutbox) == 2
        by_to = {m.to[0]: m for m in mailoutbox}
        # Client's email links to their request view; driver's to their task view.
        assert f"/requests/{sr.id}" in _html(by_to["client@example.com"])
        assert f"/driver/tasks/{sr.id}" in _html(by_to["driver@example.com"])

    def test_reviewed_emails_client_only(self, mailoutbox):
        sr = ServiceRequestFactory(status="reviewed", title="Pharmacy")
        notifications.send_status_update_email(sr, old_status="submitted")
        assert len(mailoutbox) == 1
        assert sr.client.email in mailoutbox[0].to

    def test_completed_emails_client_only(self, mailoutbox):
        driver = DriverUserFactory()
        sr = ServiceRequestFactory(driver=driver, status="completed", title="Package")
        notifications.send_status_update_email(sr, old_status="in_progress")
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [sr.client.email]

    def test_cancelled_emails_both(self, mailoutbox):
        driver = DriverUserFactory()
        sr = ServiceRequestFactory(driver=driver, status="cancelled",
                                   cancel_reason="Client changed plans")
        notifications.send_status_update_email(sr, old_status="assigned")
        assert len(mailoutbox) == 2
        assert "Client changed plans" in _html(mailoutbox[0])

    def test_unmapped_status_sends_nothing(self, mailoutbox):
        sr = ServiceRequestFactory(status="closed")
        notifications.send_status_update_email(sr, old_status="completed")
        assert len(mailoutbox) == 0


class TestDriverEmails:
    def test_application_notifies_admins(self, mailoutbox):
        AdminUserFactory(email="admin@example.com")
        profile = DriverProfileFactory()
        notifications.send_driver_application_email(profile)
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["admin@example.com"]
        assert "/admin/drivers" in _html(mailoutbox[0])

    def test_approved(self, mailoutbox):
        profile = DriverProfileFactory()
        notifications.send_driver_approved_email(profile)
        assert len(mailoutbox) == 1
        assert "approved" in mailoutbox[0].subject.lower()
        assert "/driver" in _html(mailoutbox[0])

    def test_rejected_includes_reason(self, mailoutbox):
        profile = DriverProfileFactory(rejection_reason="Incomplete documents")
        notifications.send_driver_rejected_email(profile)
        assert len(mailoutbox) == 1
        assert "Incomplete documents" in _html(mailoutbox[0])


class TestSendGuards:
    def test_no_recipients_skips(self, mailoutbox):
        # No operators exist → new-request email has no one to go to.
        client = ClientUserFactory(territory=None)
        sr = ServiceRequestFactory(client=client, status="submitted")
        notifications.send_new_request_email(sr)
        assert len(mailoutbox) == 0


class TestRegistrationTriggersWelcome:
    def test_register_sends_welcome_on_commit(self, api_client, django_capture_on_commit_callbacks, mailoutbox):
        with django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post("/api/v1/auth/register/", {
                "fullName": "New Member", "email": "newmember@example.com",
                "password": "TestPass123!", "confirmPassword": "TestPass123!",
            }, format="json")
        assert resp.status_code == 201
        assert any(m.to == ["newmember@example.com"] for m in mailoutbox)
