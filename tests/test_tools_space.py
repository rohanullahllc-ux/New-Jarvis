"""Tests for the space tools (NASA, ISS, SpaceX):  python -m unittest tests.test_tools_space -v"""
import json
import time
import unittest
from unittest import mock

import requests

from tests.tools_support import FakeResponse, ToolCase

from JarvisAdvancedBot import tools as T  # noqa: E402
from JarvisAdvancedBot.tools import space  # noqa: E402

LOGO = "https://science.nasa.gov/wp-content/themes/nasa-child/assets/images/nasa-logo@2x.png"


class PictureOfTheDayTests(ToolCase):
    def apod(self, **overrides):
        data = {"date": "2026-10-15", "title": "A Real Picture", "explanation": "First. Second. Third. Fourth.",
                "hdurl": "https://apod.nasa.gov/apod/image/2610/real_big.jpg",
                "url": "https://apod.nasa.gov/apod/image/2610/real.jpg", "media_type": "image"}
        data.update(overrides)
        self.http.routes = [("planetary/apod", FakeResponse(data))]

    def test_the_real_picture_is_opened_and_explained_in_three_sentences(self):
        self.apod()
        text = T.nasa_picture_of_the_day()
        self.assertEqual(self.opened, ["https://apod.nasa.gov/apod/image/2610/real_big.jpg"])
        self.assertIn("A Real Picture", text)
        self.assertIn("First. Second. Third.", text)
        self.assertNotIn("Fourth", text)

    def test_videos_are_opened_too(self):
        self.apod(hdurl=None, url="https://www.youtube.com/embed/abc123", media_type="video")
        T.nasa_picture_of_the_day()
        self.assertEqual(self.opened, ["https://www.youtube.com/embed/abc123"])

    def test_a_placeholder_logo_is_not_mistaken_for_the_picture(self):
        self.apod(title="NASA Science", hdurl=LOGO, url=LOGO)
        text = T.nasa_picture_of_the_day()
        self.assertEqual(self.opened, [space.APOD_PAGE])
        self.assertIn("instead", text)

    def test_when_nasas_service_is_down_the_website_is_opened(self):
        for status in (500, 429):
            self.opened.clear()
            self.http.routes = [("planetary/apod", FakeResponse({}, status))]
            self.assertIn("instead", T.nasa_picture_of_the_day())
            self.assertEqual(self.opened, [space.APOD_PAGE])

    def test_a_chosen_day(self):
        self.apod()
        T.nasa_picture_of_the_day(date="2026-10-15")
        self.assertEqual(self.http.params_for("apod")["date"], "2026-10-15")
        self.http.routes = [("planetary/apod", FakeResponse({}, 500))]
        self.opened.clear()
        T.nasa_picture_of_the_day(date="2026-10-15")
        self.assertEqual(self.opened, ["https://apod.nasa.gov/apod/ap261015.html"])
        self.fails(lambda: T.nasa_picture_of_the_day(date="yesterday"), "YYYY-MM-DD")


class MarsPhotoTests(ToolCase):
    def test_curiosity_shows_the_newest_photo(self):
        self.http.on("raw_image_items", FakeResponse({"items": [
            {"sol": 5046, "date_taken": "2026-10-16T08:12:00.000Z", "title": "Sol 5046: Chemistry & Camera (ChemCam)",
             "https_url": "https://mars.nasa.gov/msl-raw-images/new.jpg"},
            {"sol": 5045, "date_taken": "2026-10-15T08:12:00.000Z", "title": "Sol 5045: Mast Camera",
             "https_url": "https://mars.nasa.gov/msl-raw-images/old.jpg"}]}))
        text = T.nasa_mars_photos(rover="curiosity")
        self.assertEqual(self.opened, ["https://mars.nasa.gov/msl-raw-images/new.jpg"])
        for piece in ("Curiosity", "Martian day 5046", "16 October 2026", "Chemistry & Camera (ChemCam)"):
            self.assertIn(piece, text)
        params = self.http.params_for("raw_image_items")
        self.assertEqual((params["condition_1"], params["order"]), ("msl:mission", "sol desc"))

    def test_perseverance_uses_its_own_feed(self):
        self.http.on("rss/api", FakeResponse({"images": [
            {"sol": 2010, "date_taken_utc": "2026-10-15T22:15:33.982", "title": "Mars Perseverance Sol 2010: Left Navigation Camera (Navcam)",
             "image_files": {"large": "https://mars.nasa.gov/mars2020-raw-images/big.jpg"}}]}))
        text = T.nasa_mars_photos(rover="perseverance")
        self.assertEqual(self.opened, ["https://mars.nasa.gov/mars2020-raw-images/big.jpg"])
        self.assertIn("Perseverance's newest photo is from Martian day 2010, taken on 15 October 2026 with Left Navigation Camera (Navcam)", text)
        self.assertEqual(self.http.params_for("rss/api")["category"], "mars2020")

    def test_photos_without_a_picture_link_are_skipped_and_an_empty_feed_is_an_error(self):
        self.http.on("raw_image_items", FakeResponse({"items": [{"sol": 1, "title": "Sol 1: x"}]}))
        self.fails(lambda: T.nasa_mars_photos(rover="curiosity"), "no recent Curiosity photos")
        self.assertEqual(self.opened, [])


class SolarBodyTests(ToolCase):
    def test_every_body_gets_a_complete_fact_sheet(self):
        for key, body in space.BODIES.items():
            text = T.nasa_solar_body_facts(body=key)
            self.assertTrue(text.lower().startswith(body["name"].lower()), key)
            for piece in ("Radius", "surface gravity", "One turn on its axis takes", "Temperature:"):
                self.assertIn(piece, text, key)
            self.assertNotIn("  ", text)
            self.assertTrue(text.endswith("."), key)

    def test_names_are_understood_loosely(self):
        for name in ("the moon", "The Moon", " MARS ", "planet Venus", "Jupiter's", "Pluto planet"):
            self.assertTrue(T.nasa_solar_body_facts(body=name), name)

    def test_gravity_is_compared_with_earths(self):
        self.assertIn("(100 percent of Earth's)", T.nasa_solar_body_facts(body="Earth"))
        self.assertIn("(16 percent of Earth's)", T.nasa_solar_body_facts(body="the Moon"))

    def test_unknown_bodies_are_explained(self):
        self.fails(lambda: T.nasa_solar_body_facts(body="Krypton"), "Sun, the Moon")


def rock(name, miss_km, metres, hazardous, stamp="2026-Oct-17 03:03"):
    return {"name": name, "is_potentially_hazardous_asteroid": hazardous,
            "estimated_diameter": {"meters": {"estimated_diameter_max": metres}},
            "close_approach_data": [{"close_approach_date": "2026-10-17", "close_approach_date_full": stamp,
                                     "miss_distance": {"kilometers": str(miss_km)}}]}


class AsteroidTests(ToolCase):
    def feed(self, *days):
        self.http.on("neo/rest/v1/feed", FakeResponse({"near_earth_objects": {f"2026-10-{17 + i}": day for i, day in enumerate(days)}}))

    def test_the_summary_names_the_closest_and_biggest_in_plain_words(self):
        self.feed([rock("(2005 VS)", 15738548.2, 80, False), rock("144900 (2004 VG64)", 40000000, 1318.4, True)],
                  [rock("(2026 AB)", 60000000, 12, False)])
        text = T.nasa_near_earth_objects()
        for piece in ("3 near-Earth asteroids", "The closest, 2005 VS, passes at 15,738,548 kilometres",
                      "40.9 times the distance to the Moon", "The biggest, 144900 2004 VG64, is up to 1,318 metres",
                      "1 of them is classed as potentially hazardous"):
            self.assertIn(piece, text)
        self.assertNotIn("(2005", text)
        self.assertNotIn("(2004", text)
        self.assertNotIn("2026-Oct", text)
        self.assertIn("October", text)

    def test_none_hazardous(self):
        self.feed([rock("(2005 VS)", 1000000, 80, False)])
        self.assertIn("None are classed as potentially hazardous", T.nasa_near_earth_objects())

    def test_a_quiet_week(self):
        self.feed([])
        self.assertIn("no near-Earth asteroids", T.nasa_near_earth_objects(start_date="2026-10-17", end_date="2026-10-19"))
        params = self.http.params_for("neo/rest/v1/feed")
        self.assertEqual((params["start_date"], params["end_date"]), ("2026-10-17", "2026-10-19"))

    def test_the_date_range_is_checked_before_asking_nasa(self):
        self.fails(lambda: T.nasa_near_earth_objects(start_date="2026-10-17", end_date="2026-10-30"), "at most 7 days")
        self.fails(lambda: T.nasa_near_earth_objects(start_date="2026-10-17", end_date="2026-10-10"), "before the start")
        self.fails(lambda: T.nasa_near_earth_objects(start_date="soon"), "YYYY-MM-DD")
        self.assertEqual(self.http.calls, [])

    def test_running_out_of_the_shared_demo_key_says_how_to_fix_it(self):
        self.http.on("neo/rest/v1/feed", FakeResponse({}, 429))
        with mock.patch.object(space.config, "NASA_API_KEY", "DEMO_KEY"):
            self.fails(lambda: T.nasa_near_earth_objects(), "too many times", "api.nasa.gov")
        with mock.patch.object(space.config, "NASA_API_KEY", "my-own-key"):
            message = self.fails(lambda: T.nasa_near_earth_objects(), "too many times")
            self.assertNotIn("api.nasa.gov", message)


class IssTests(ToolCase):
    def setUp(self):
        super().setUp()
        self.http.on("wheretheiss.at", FakeResponse({"latitude": -30.04, "longitude": 112.41, "altitude": 426.2,
                                                     "velocity": 27566.3, "visibility": "daylight"}))

    def test_over_a_country(self):
        self.http.on("nominatim", FakeResponse({"display_name": "Pakistan"}))
        text = T.get_iss_location()
        self.assertEqual(text, "The International Space Station is over Pakistan, 426 kilometres up, travelling at "
                               "27,566 kilometres an hour, in sunlight.")
        self.assertEqual(self.http.params_for("nominatim")["accept-language"], "en")

    def test_over_open_water_the_coordinates_are_given(self):
        self.http.on("nominatim", FakeResponse({"error": "Unable to geocode"}))
        self.assertIn("over open water, at 30.0 degrees south, 112.4 degrees east", T.get_iss_location())

    def test_without_the_place_lookup_the_coordinates_are_still_given(self):
        self.http.on("nominatim", FakeResponse({}, 500))
        self.assertIn("at 30.0 degrees south, 112.4 degrees east", T.get_iss_location())


class SpaceXTests(ToolCase):
    LAUNCH = {"name": "Falcon 9 Block 5 | USSF-481", "net": "2026-10-16T12:01:00Z",
              "pad": {"name": "Space Launch Complex 4E"}, "status": {"name": "Launch Successful"}}

    def test_the_latest_launch(self):
        self.http.on("launch/previous", FakeResponse({"results": [self.LAUNCH]}))
        text = T.spacex_latest_launch(which="latest")
        for piece in ("latest launch was USSF-481 on a Falcon 9 Block 5", "from Space Launch Complex 4E", "Result: Launch Successful"):
            self.assertIn(piece, text)
        self.assertEqual(self.http.params_for("launch/previous")["lsp__name"], "SpaceX")

    def test_the_next_launch(self):
        self.http.on("launch/upcoming", FakeResponse({"results": [dict(self.LAUNCH, status={"name": "Go for Launch"})]}))
        text = T.spacex_latest_launch(which="next")
        self.assertIn("next launch is USSF-481 on a Falcon 9 Block 5, scheduled for", text)
        self.assertIn("Status: Go for Launch", text)

    def test_unconfirmed_dates_and_missing_missions_are_handled(self):
        self.http.on("launch/upcoming", FakeResponse({"results": [{"name": "Starship Flight 12", "net": None}]}))
        text = T.spacex_latest_launch(which="next")
        self.assertIn("a date that isn't confirmed yet", text)
        self.assertIn("Starship Flight 12", text)

    def test_no_launches_is_an_error(self):
        self.http.on("launch/previous", FakeResponse({"results": []}))
        self.fails(lambda: T.spacex_latest_launch(which="latest"), "no SpaceX launch")

    def test_the_launch_service_is_asked_once_because_it_allows_only_a_few_requests_an_hour(self):
        self.http.on("launch/previous", FakeResponse({"results": [self.LAUNCH]}))
        T.spacex_latest_launch(which="latest")
        T.spacex_latest_launch(which="latest")
        self.assertEqual(len(self.http.calls), 1)

    def test_company_facts(self):
        self.http.on("agencies/121", FakeResponse({"founding_year": 2002, "administrator": "CEO: Elon Musk",
                                                   "total_launch_count": 739, "successful_launches": 724,
                                                   "failed_launches": 15, "successful_landings": 684}))
        text = T.spacex_company_info()
        for piece in ("founded in 2002", "led by Elon Musk", "739 launches", "724 successful", "684 times"):
            self.assertIn(piece, text)


class StarlinkTests(ToolCase):
    CSV = "OBJECT_NAME,OBJECT_ID,EPOCH\nSTARLINK-1,2019-074A,2026-10-17\nSTARLINK-2,2019-074B,2026-10-17\n\n"

    def cache_file(self):
        return self.db / "Cache" / "starlink.json"

    def test_the_count_is_downloaded_once_then_remembered(self):
        self.http.on("celestrak.org", FakeResponse(text=self.CSV))
        self.assertEqual(T.spacex_starlink_count(), "There are about 2 Starlink satellites in orbit, according to CelesTrak.")
        self.assertEqual(json.loads(self.cache_file().read_text())["count"], 2)
        self.http.routes = [("celestrak.org", AssertionError("must not be asked again"))]
        self.assertIn("about 2 Starlink", T.spacex_starlink_count())

    def write_cache(self, count, age_hours):
        self.cache_file().parent.mkdir(parents=True)
        self.cache_file().write_text(json.dumps({"count": count, "fetched": time.time() - age_hours * 3600}))

    def test_an_old_count_is_better_than_none_when_the_service_refuses(self):
        self.write_cache(7000, age_hours=13)
        self.http.on("celestrak.org", FakeResponse(text="GP data has not updated", status=403))
        text = T.spacex_starlink_count()
        self.assertIn("when I last checked there were about 7,000", text)

    def test_a_refusal_with_nothing_remembered_explains_the_two_hour_rule(self):
        self.http.on("celestrak.org", FakeResponse(text="GP data has not updated", status=403))
        self.fails(lambda: T.spacex_starlink_count(), "once every two hours")

    def test_other_failures_pass_through(self):
        self.http.on("celestrak.org", FakeResponse(text="down", status=503))
        self.fails(lambda: T.spacex_starlink_count(), "celestrak.org", "problems")

    def test_an_unreadable_list_is_not_stored(self):
        self.http.on("celestrak.org", FakeResponse(text="<html>maintenance</html>"))
        self.fails(lambda: T.spacex_starlink_count(), "couldn't read")
        self.assertFalse(self.cache_file().exists())

    def test_a_damaged_cache_file_is_ignored(self):
        self.cache_file().parent.mkdir(parents=True)
        self.cache_file().write_text("{ not json")
        self.http.on("celestrak.org", FakeResponse(text=self.CSV))
        self.assertIn("about 2 Starlink", T.spacex_starlink_count())


if __name__ == "__main__":
    unittest.main()
