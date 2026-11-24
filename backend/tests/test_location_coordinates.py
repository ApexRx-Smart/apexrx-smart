"""Branch and depot coordinates: chosen on a map in the browser, but checked
here. Both or neither, and only inside Rwanda; they are stored with the
organization and the branch they were sent for."""

import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.helpers import location, organization, user

KIGALI = {"latitude": -1.9441, "longitude": 30.0619}


@pytest.fixture
def owner(client):
    h = user(client, "owner@map.example.com", account_type="pharmacy")
    return h, organization(client, h, "pharmacy", "Map Pharmacy")


def _stored(location_id):
    with engine.connect() as c:
        return c.execute(text("SELECT organization_id, latitude, longitude FROM location WHERE location_id = :l"),
                         {"l": location_id}).one()


def test_a_point_in_rwanda_is_saved_on_the_right_branch(client, owner):
    h, org = owner
    r = client.post(f"/organizations/{org}/locations", json={"name": "Downtown", **KIGALI}, headers=h)
    assert r.status_code == 201, r.text
    loc = r.json()
    stored = _stored(loc["location_id"])
    assert stored.organization_id == org
    assert (float(stored.latitude), float(stored.longitude)) == (-1.9441, 30.0619)


@pytest.mark.parametrize("lat,lng", [
    (0.3476, 32.5825),    # Kampala
    (-1.2921, 36.8219),   # Nairobi
    (-1.9441, 33.0),      # east of Rwanda
    (-3.5, 29.9),         # south of Rwanda
    (0.0, 0.0),
])
def test_points_outside_rwanda_are_refused_on_create_and_update(client, owner, lat, lng):
    h, org = owner
    r = client.post(f"/organizations/{org}/locations", json={"name": "Elsewhere", "latitude": lat, "longitude": lng}, headers=h)
    assert r.status_code == 422 and "Rwanda" in r.text
    loc = client.post(f"/organizations/{org}/locations", json={"name": "Downtown", **KIGALI}, headers=h).json()
    r = client.patch(f"/organizations/{org}/locations/{loc['location_id']}", json={"latitude": lat, "longitude": lng}, headers=h)
    assert r.status_code == 422
    stored = _stored(loc["location_id"])
    assert (float(stored.latitude), float(stored.longitude)) == (-1.9441, 30.0619)  # unchanged


def test_every_new_branch_needs_a_location(client, owner):
    h, org = owner
    r = client.post(f"/organizations/{org}/locations", json={"name": "Remera"}, headers=h)
    assert r.status_code == 422 and "Place the branch on the map" in r.text
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM location WHERE organization_id = :o"), {"o": org}).scalar() == 0


def test_a_location_is_moved_never_removed(client, owner):
    h, org = owner
    loc = client.post(f"/organizations/{org}/locations", json={"name": "Remera", **KIGALI}, headers=h).json()
    r = client.patch(f"/organizations/{org}/locations/{loc['location_id']}",
                     json={"latitude": -1.9577, "longitude": 30.1127}, headers=h)
    assert r.status_code == 200 and float(r.json()["latitude"]) == -1.9577
    # Other fields can change without touching the location.
    r = client.patch(f"/organizations/{org}/locations/{loc['location_id']}", json={"address": "KG 17 Ave"}, headers=h)
    assert float(r.json()["longitude"]) == 30.1127
    r = client.patch(f"/organizations/{org}/locations/{loc['location_id']}",
                     json={"latitude": None, "longitude": None}, headers=h)
    assert r.status_code == 422 and "cannot be removed" in r.text
    assert float(_stored(loc["location_id"]).latitude) == -1.9577


def test_a_branch_saved_before_locations_were_required_keeps_working_and_can_be_placed(client, owner):
    h, org = owner
    loc_id = location(client, h, org, "Old Branch", on_map=False)
    # Still usable: other details change without a location ...
    r = client.patch(f"/organizations/{org}/locations/{loc_id}", json={"address": "KN 4 Ave"}, headers=h)
    assert r.status_code == 200 and r.json()["latitude"] is None
    # ... and the owner places it on the map.
    r = client.patch(f"/organizations/{org}/locations/{loc_id}", json={"latitude": -1.95, "longitude": 30.06}, headers=h)
    assert r.status_code == 200 and float(r.json()["latitude"]) == -1.95


def test_both_coordinates_or_neither(client, owner):
    h, org = owner
    assert client.post(f"/organizations/{org}/locations", json={"name": "Half", "latitude": -1.95}, headers=h).status_code == 422
    assert client.post(f"/organizations/{org}/locations",
                       json={"name": "Half", "latitude": -1.95, "longitude": None}, headers=h).status_code == 422


def test_another_organization_cannot_place_this_organizations_branch(client, owner):
    h, org = owner
    loc = client.post(f"/organizations/{org}/locations", json={"name": "Downtown", **KIGALI}, headers=h).json()
    other = user(client, "other@map.example.com", account_type="pharmacy")
    organization(client, other, "pharmacy", "Other Pharmacy")
    r = client.patch(f"/organizations/{org}/locations/{loc['location_id']}", json={"latitude": -2.0, "longitude": 30.0},
                     headers=other)
    assert r.status_code == 404
    stored = _stored(loc["location_id"])
    assert (float(stored.latitude), float(stored.longitude)) == (-1.9441, 30.0619)
