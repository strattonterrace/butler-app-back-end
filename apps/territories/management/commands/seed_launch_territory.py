"""Management command — seed the launch territory (Orange County) + ZIPs.

Runs in the Render build step (after migrate), like ensure_admin, so prod has
a served area the moment it deploys. Without it the onboarding location gate
matches nothing and waitlists every visitor.

Kept as a command (not a data migration) so it runs on deploy but never
populates the test database — test fixtures create their own territories and a
seeded 'Orange County, CA' row would collide with the unique name constraint.

Idempotent: update_or_create on name never duplicates and never clears an
operator that may already be assigned.
"""
from django.core.management.base import BaseCommand

from apps.territories.models import Territory

LAUNCH_TERRITORY = "Orange County, CA"

# Broad set of Orange County ZIPs across major cities so early testers pass
# the gate regardless of which OC city they're in.
ORANGE_COUNTY_ZIPS = sorted(set([
    "92602", "92603", "92604", "92606", "92612", "92614", "92618", "92620",  # Irvine
    "92660", "92661", "92662", "92663",                                      # Newport Beach
    "92626", "92627",                                                        # Costa Mesa
    "92780", "92782",                                                        # Tustin
    "92701", "92703", "92704", "92705", "92706", "92707",                    # Santa Ana
    "92801", "92802", "92804", "92805", "92806", "92807", "92808",           # Anaheim
    "92646", "92647", "92648", "92649",                                      # Huntington Beach
    "92831", "92832", "92833", "92835",                                      # Fullerton
    "92866", "92867", "92868", "92869",                                      # Orange
    "92840", "92841", "92843", "92844",                                      # Garden Grove
    "92691", "92692", "92630", "92610",                                      # Mission Viejo / Lake Forest
    "92651", "92656", "92677",                                               # Laguna / Aliso Viejo
]))


class Command(BaseCommand):
    help = "Seed the launch territory (Orange County) with its served ZIP codes."

    def handle(self, *args, **options):
        territory, created = Territory.objects.update_or_create(
            name=LAUNCH_TERRITORY,
            defaults={"zip_codes": ORANGE_COUNTY_ZIPS, "status": "active"},
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} territory '{territory.name}' with {len(territory.zip_codes)} ZIPs."
        ))
