"""Tests for the world tools (facts, games, mail, Wi-Fi, downloads, gags):  python -m unittest tests.test_tools_world -v"""
import io
import smtplib
import sys
import unittest
from contextlib import redirect_stdout
from types import ModuleType, SimpleNamespace
from unittest import mock

from tests.tools_support import FakeResponse, ToolCase

from anthropic.lib.tools import ToolError  # noqa: E402
from JarvisAdvancedBot import tools as T  # noqa: E402
from JarvisAdvancedBot.tools import _common, world  # noqa: E402


class IdeasAndFactsTests(ToolCase):
    def names_in(self, text):
        return text.split(": ", 1)[1].split(". ", 1)[0].split(", ")

    def test_business_names_are_built_around_the_keyword(self):
        text = T.generate_business_names(keyword="coffee", count=5)
        names = self.names_in(text)
        self.assertEqual(len(names), 5)
        self.assertEqual(len(set(names)), 5)
        self.assertTrue(all("Coffee" in name for name in names), names)
        self.assertIn("haven't checked", text)
        self.assertEqual(self.http.calls, [])                          # fully offline

    def test_business_name_count_is_kept_sensible(self):
        self.assertEqual(len(self.names_in(T.generate_business_names(keyword="tea", count=99))), 10)
        self.assertEqual(len(self.names_in(T.generate_business_names(keyword="tea", count=0))), 1)

    def test_two_word_keywords_use_both_words(self):
        for _ in range(20):
            names = self.names_in(T.generate_business_names(keyword="fitness app", count=10))
            self.assertTrue(all("Fitness" in n or "App" in n for n in names), names)

    def test_business_names_need_real_words(self):
        self.fails(lambda: T.generate_business_names(keyword="123"), "word or two")

    def test_random_fact_prefers_the_general_service_and_falls_back_to_cats(self):
        self.http.on("uselessfacts", FakeResponse({"text": " Bananas are berries. "}))
        self.assertEqual(T.get_random_fact(), "Bananas are berries.")
        self.http.routes = [("uselessfacts", FakeResponse({}, 500)), ("catfact.ninja", FakeResponse({"fact": "Cats purr."}))]
        self.assertEqual(T.get_random_fact(), "Cats purr.")
        self.http.routes = [("uselessfacts", FakeResponse({"text": ""})), ("catfact.ninja", FakeResponse({"fact": "Cats purr."}))]
        self.assertEqual(T.get_random_fact(), "Cats purr.")

    def test_cat_facts_do_not_touch_the_general_service(self):
        self.http.on("catfact.ninja", FakeResponse({"fact": "Cats purr."}))
        self.assertEqual(T.get_random_fact(topic="cat"), "Cats purr.")
        self.assertEqual(len(self.http.calls), 1)

    def test_random_fact_errors_when_everything_is_down(self):
        self.http.on("uselessfacts", FakeResponse({}, 500))
        self.http.on("catfact.ninja", FakeResponse({}, 500))
        self.fails(lambda: T.get_random_fact(), "catfact.ninja")

    def test_activity_suggestions_use_the_service_and_work_offline_too(self):
        self.http.on("bored-api", FakeResponse({"activity": "Organize your movie collection", "type": "busywork", "participants": 1}))
        self.assertEqual(T.get_random_activity(), "How about this: Organize your movie collection. (busywork, 1 person)")
        self.http.routes = [("bored-api", FakeResponse({"activity": "Play chess", "type": "social", "participants": 2}))]
        self.assertIn("(social, 2 people)", T.get_random_activity())
        self.http.routes = [("bored-api", FakeResponse({}, 500))]
        offline = T.get_random_activity()
        self.assertTrue(any(activity in offline for activity, _, _ in world.OFFLINE_ACTIVITIES), offline)

    def test_advice(self):
        self.http.on("adviceslip", FakeResponse({"slip": {"id": 1, "advice": "Be kind."}}))
        self.assertEqual(T.get_random_advice(), "Be kind.")
        self.http.routes = [("adviceslip", FakeResponse({"message": {"type": "error"}}))]
        self.fails(lambda: T.get_random_advice(), "empty answer")

    def test_jokes_come_online_or_from_the_built_in_list(self):
        self.http.on("icanhazdadjoke", FakeResponse({"joke": " Why did the chicken cross the road? "}))
        self.assertEqual(T.get_joke(), "Why did the chicken cross the road?")
        self.http.routes = [("icanhazdadjoke", FakeResponse({}, 503))]
        self.assertIn(T.get_joke(), world.OFFLINE_JOKES)

    def test_dog_photos_name_the_breed(self):
        self.http.on("dog.ceo", FakeResponse({"status": "success", "message": "https://images.dog.ceo/breeds/hound-afghan/n02088094_1003.jpg"}))
        self.assertEqual(T.get_dog_image(), "Opened a random dog photo. Breed: afghan hound.")
        self.assertEqual(self.opened, ["https://images.dog.ceo/breeds/hound-afghan/n02088094_1003.jpg"])
        self.http.routes = [("dog.ceo", FakeResponse({"status": "success", "message": "https://images.dog.ceo/breeds/mix/x.jpg"}))]
        self.assertIn("Breed: mixed breed.", T.get_dog_image())
        self.http.routes = [("dog.ceo", FakeResponse({"status": "error"}))]
        self.opened.clear()
        self.fails(lambda: T.get_dog_image(), "didn't send a picture")
        self.assertEqual(self.opened, [])


class PartyTrickTests(ToolCase):
    def test_the_cracking_show_is_pure_fiction(self):
        text = T.password_cracking_demo(password_length=6)
        self.assertIn("pretend", text)
        self.assertIn("nothing real", text)
        self.assertIn("a password with 6 characters", text)
        found = text.split("Found it: ")[1].split(".")[0]
        self.assertEqual(len(found), 6)
        self.assertTrue(found.isalnum())
        self.assertEqual(self.http.calls, [])

    def test_the_made_up_password_is_different_each_time_and_its_length_is_limited(self):
        lengths = {len(T.password_cracking_demo(password_length=n).split("Found it: ")[1].split(".")[0]) for n in (1, 8, 99)}
        self.assertEqual(lengths, {4, 8, 12})
        shows = {T.password_cracking_demo() for _ in range(5)}
        self.assertGreater(len(shows), 1)

    def test_the_hacking_skit_uses_a_made_up_english_speaking_person_and_reveals_no_password(self):
        self.http.on("randomuser.me", FakeResponse({"results": [{
            "name": {"first": "Herbert", "last": "Graham"},
            "location": {"city": "Salisbury", "state": "Leicestershire", "country": "United Kingdom"},
            "email": "herbert.graham@example.com", "dob": {"age": 60},
            "login": {"username": "smallzebra896", "password": "hunter2"}}]}))
        text = T.hack_a_random_profile()
        for piece in ("Herbert Graham", "aged 60", "Salisbury", "smallzebra896", "made-up person", "nobody was hacked"):
            self.assertIn(piece, text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("password", text.lower())
        self.assertIn("us", self.http.params_for("randomuser.me")["nat"])
        self.http.routes = [("randomuser.me", FakeResponse({"results": []}))]
        self.fails(lambda: T.hack_a_random_profile(), "target")


def fake_instaloader(url="https://cdn.example/pic.jpg", error=None):
    module = ModuleType("instaloader")

    class ProfileNotExistsException(Exception):
        pass

    module.exceptions = SimpleNamespace(ProfileNotExistsException=ProfileNotExistsException)

    class Instaloader:
        def __init__(self, **options):
            self.context = "context"

    class Profile:
        @staticmethod
        def from_username(context, name):
            if error == "missing":
                raise ProfileNotExistsException(name)
            if error:
                raise ConnectionError(error)
            return SimpleNamespace(profile_pic_url=url)

    module.Instaloader, module.Profile = Instaloader, Profile
    return module


class InstagramTests(ToolCase):
    def picture(self, **kwargs):
        return mock.patch.dict(sys.modules, {"instaloader": fake_instaloader(**kwargs)})

    def test_the_picture_is_saved_in_the_downloads_folder(self):
        self.http.on("cdn.example", FakeResponse(content=b"\xff\xd8jpegbytes"))
        with self.picture():
            text = T.instagram_profile_picture(username="@natgeo")
        self.assertEqual((self.db / "Downloads" / "Instagram" / "natgeo.jpg").read_bytes(), b"\xff\xd8jpegbytes")
        self.assertIn("natgeo", text)
        self.assertEqual(self.opened, [])

    def test_only_real_looking_usernames_are_accepted(self):
        for name in ("bad name", "a/b", "x" * 31, "", "name;rm"):
            self.fails(lambda: T.instagram_profile_picture(username=name), "letters, numbers")
        self.assertEqual(self.http.calls, [])

    def test_just_opening_the_profile_needs_no_download_library(self):
        with mock.patch.dict(sys.modules, {"instaloader": None}):
            T.instagram_profile_picture(username="natgeo", download=False)
        self.assertEqual(self.opened, ["https://www.instagram.com/natgeo/"])

    def test_when_instagram_refuses_the_profile_page_is_opened_instead(self):
        with self.picture(error="Please wait a few minutes before you try again"):
            text = T.instagram_profile_picture(username="natgeo")
        self.assertEqual(self.opened, ["https://www.instagram.com/natgeo/"])
        self.assertIn("wouldn't let me", text)
        self.assertFalse((self.db / "Downloads" / "Instagram" / "natgeo.jpg").exists())

    def test_a_failed_image_download_is_handled_the_same_way(self):
        self.http.on("cdn.example", FakeResponse({}, 403))
        with self.picture():
            self.assertIn("wouldn't let me", T.instagram_profile_picture(username="natgeo"))
        self.assertEqual(self.opened, ["https://www.instagram.com/natgeo/"])

    def test_an_account_that_does_not_exist(self):
        with self.picture(error="missing"):
            self.fails(lambda: T.instagram_profile_picture(username="zzzznoone"), "no Instagram account called zzzznoone")

    def test_a_missing_library_is_explained(self):
        with mock.patch.dict(sys.modules, {"instaloader": None}):
            self.fails(lambda: T.instagram_profile_picture(username="natgeo"), "pip install instaloader")


class FakeSMTP:
    instances = []
    login_error = None
    send_error = None
    secure_from_start = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.tls, self.login_args, self.sent, self.closed = host, port, False, None, [], False
        FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.login_error:
            raise FakeSMTP.login_error
        self.login_args = (user, password)

    def send_message(self, message):
        if FakeSMTP.send_error:
            raise FakeSMTP.send_error
        self.sent.append(message)

    def quit(self):
        self.closed = True


class FakeSMTPSSL(FakeSMTP):
    secure_from_start = True


class EmailTests(ToolCase):
    def setUp(self):
        super().setUp()
        FakeSMTP.instances, FakeSMTP.login_error, FakeSMTP.send_error = [], None, None
        for patcher in (
            mock.patch.multiple(world.config, EMAIL_ADDRESS="me@gmail.com", EMAIL_PASSWORD="app-pass-1234",
                                EMAIL_SMTP_HOST="", EMAIL_SMTP_PORT=587),
            mock.patch.object(smtplib, "SMTP", FakeSMTP),
            mock.patch.object(smtplib, "SMTP_SSL", FakeSMTPSSL),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self, **kwargs):
        arguments = {"to": "a@example.com", "subject": "Hello", "body": "Hi there", "confirmed": True}
        arguments.update(kwargs)
        return T.send_email(**arguments)

    def test_a_confirmed_email_is_sent_once_over_a_secured_connection(self):
        text = self.send(to="a@example.com, b@example.org")
        self.assertEqual(text, "Sent your email to a@example.com, b@example.org.")
        smtp, = FakeSMTP.instances
        self.assertEqual((smtp.host, smtp.port, smtp.tls), ("smtp.gmail.com", 587, True))
        self.assertEqual(smtp.login_args, ("me@gmail.com", "app-pass-1234"))
        self.assertTrue(smtp.closed)
        message, = smtp.sent
        self.assertEqual((message["From"], message["To"], message["Subject"]), ("me@gmail.com", "a@example.com, b@example.org", "Hello"))
        self.assertEqual(message.get_content().strip(), "Hi there")

    def test_nothing_is_sent_until_the_user_has_confirmed(self):
        message = self.fails(lambda: self.send(confirmed=False), "confirm", "a@example.com", "Hello")
        self.assertIn("confirmed set to true", message)
        self.assertEqual(FakeSMTP.instances, [])

    def test_mail_servers_follow_the_senders_address(self):
        for address, host in (("me@yahoo.com", "smtp.mail.yahoo.com"), ("me@outlook.com", "smtp-mail.outlook.com"),
                              ("me@icloud.com", "smtp.mail.me.com"), ("me@company.org", "smtp.company.org")):
            FakeSMTP.instances.clear()
            with mock.patch.object(world.config, "EMAIL_ADDRESS", address):
                self.send()
            self.assertEqual(FakeSMTP.instances[0].host, host, address)

    def test_a_configured_server_and_port_win_and_port_465_is_secure_from_the_start(self):
        with mock.patch.multiple(world.config, EMAIL_SMTP_HOST="mail.relay.net", EMAIL_SMTP_PORT=465):
            self.send()
        smtp, = FakeSMTP.instances
        self.assertEqual((smtp.host, smtp.port, smtp.secure_from_start, smtp.tls), ("mail.relay.net", 465, True, False))

    def test_the_account_must_be_set_up(self):
        with mock.patch.object(world.config, "EMAIL_PASSWORD", ""):
            self.fails(lambda: self.send(), ".env")
        with mock.patch.object(world.config, "EMAIL_ADDRESS", ""):
            self.fails(lambda: self.send(), ".env")
        self.assertEqual(FakeSMTP.instances, [])

    def test_recipients_and_message_are_checked(self):
        self.fails(lambda: self.send(to="not-an-address"), "valid email addresses")
        self.fails(lambda: self.send(to=""), "valid email addresses")
        self.fails(lambda: self.send(to=",".join(f"u{i}@example.com" for i in range(6))), "valid email addresses")
        self.fails(lambda: self.send(body="   "), "no message")
        self.assertEqual(FakeSMTP.instances, [])

    def test_a_subject_cannot_smuggle_in_extra_headers(self):
        self.send(subject="Hi\r\nBcc: evil@example.com")
        message = FakeSMTP.instances[0].sent[0]
        self.assertEqual(message["Subject"], "Hi Bcc: evil@example.com")
        self.assertIsNone(message["Bcc"])

    def test_files_can_be_attached(self):
        report = self.db / "report.pdf"
        report.write_bytes(b"%PDF-1.4 fake")
        self.send(attachment_path=str(report))
        message = FakeSMTP.instances[0].sent[0]
        attachment, = list(message.iter_attachments())
        self.assertEqual((attachment.get_filename(), attachment.get_content_type()), ("report.pdf", "application/pdf"))
        self.assertEqual(attachment.get_content(), b"%PDF-1.4 fake")

    def test_private_files_are_never_attached(self):
        secret = self.db / ".env"
        secret.write_text("ANTHROPIC_API_KEY=sk-secret")
        face = self.db / "FaceDetectionModule"
        face.mkdir()
        (face / "trainer.yml").write_text("biometric")
        for path in (secret, face / "trainer.yml"):
            self.fails(lambda: self.send(attachment_path=str(path)), "private settings or face data")
        self.assertEqual(FakeSMTP.instances, [])

    def test_missing_and_oversized_attachments_are_refused(self):
        self.fails(lambda: self.send(attachment_path=str(self.db / "nope.pdf")), "can't find")
        big = self.db / "big.bin"
        big.write_bytes(b"x" * 11)
        with mock.patch.object(world, "MAX_ATTACHMENT_BYTES", 10):
            self.fails(lambda: self.send(attachment_path=str(big)), "20 megabytes")

    def test_a_refused_login_explains_app_passwords_and_never_shows_the_password(self):
        FakeSMTP.login_error = smtplib.SMTPAuthenticationError(535, b"bad credentials app-pass-1234")
        message = self.fails(lambda: self.send(), "app password")
        self.assertNotIn("app-pass-1234", message)
        self.assertTrue(FakeSMTP.instances[0].closed)

    def test_other_sending_problems(self):
        FakeSMTP.send_error = smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no such user")})
        self.fails(lambda: self.send(), "rejected the recipient")
        FakeSMTP.send_error = OSError("network is unreachable")
        self.fails(lambda: self.send(), "couldn't send the email", "smtp.gmail.com")


PROFILES = """
Profiles on interface Wi-Fi:

Group policy profiles (read only)
---------------------------------
    <None>

User profiles
-------------
    All User Profile     : Home Net
    All User Profile     : Home Net 5G
    All User Profile     : Cafe
"""
KEY_OUTPUT = """
Profile Cafe on interface Wi-Fi:
=======================================================================

Security settings
-----------------
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Security key           : Present
    Key Content            : {password}
"""


class WifiTests(ToolCase):
    def setUp(self):
        super().setUp()
        self.key_text = KEY_OUTPUT.format(password="s3cret Pass!")
        self.asked = []

        def fake_netsh(*arguments):
            self.asked.append(arguments)
            return PROFILES if arguments[:2] == ("show", "profiles") else self.key_text

        patcher = mock.patch.object(world, "_netsh", fake_netsh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def reveal(self, ssid):
        out = io.StringIO()
        with mock.patch.object(world, "copy_to_clipboard") as clipboard, redirect_stdout(out):
            text = T.get_saved_wifi_password(ssid=ssid)
        return text, out.getvalue(), clipboard

    def test_without_a_name_the_saved_networks_are_listed_and_no_secret_is_read(self):
        self.assertEqual(T.get_saved_wifi_password(), "Saved Wi-Fi networks: Home Net, Home Net 5G, Cafe. "
                                                      "Tell me which one you want the password for.")
        self.assertEqual(self.asked, [("show", "profiles")])

    def test_the_password_goes_to_the_screen_and_clipboard_but_not_into_the_reply(self):
        text, screen, clipboard = self.reveal("cafe")
        self.assertNotIn("s3cret Pass!", text)
        self.assertIn("on your screen and on the clipboard", text)
        self.assertIn("Wi-Fi password for Cafe: s3cret Pass!", screen)
        clipboard.assert_called_once_with("s3cret Pass!")
        self.assertIn(("show", "profile", "name=Cafe", "key=clear"), self.asked)

    def test_an_exact_name_beats_a_longer_name_that_contains_it(self):
        self.key_text = KEY_OUTPUT.format(password="home-pass")
        text, screen, _ = self.reveal("home net")
        self.assertIn("Wi-Fi password for Home Net: home-pass", screen)
        self.assertIn(("show", "profile", "name=Home Net", "key=clear"), self.asked)

    def test_a_partial_name_works_when_only_one_network_matches(self):
        _, screen, _ = self.reveal("caf")
        self.assertIn("for Cafe:", screen)

    def test_an_ambiguous_or_unknown_name_is_explained(self):
        self.fails(lambda: self.reveal("home"), "Several saved networks match", "Home Net 5G")
        self.fails(lambda: self.reveal("airport"), "no saved network called airport", "Cafe")

    def test_when_windows_withholds_the_key(self):
        self.key_text = "Security key           : Present\n"
        self.fails(lambda: self.reveal("cafe"), "didn't give me a password")

    def test_if_the_clipboard_is_unavailable_the_screen_still_has_it(self):
        out = io.StringIO()
        with mock.patch.object(world, "copy_to_clipboard", side_effect=ToolError("busy")), redirect_stdout(out):
            text = T.get_saved_wifi_password(ssid="cafe")
        self.assertIn("on your screen", text)
        self.assertNotIn("clipboard", text)
        self.assertIn("s3cret Pass!", out.getvalue())



class NetshTests(ToolCase):
    def test_netsh_is_run_without_a_shell_and_failures_are_explained(self):
        with mock.patch("subprocess.run", return_value=SimpleNamespace(stdout="listing")) as run:
            self.assertEqual(world._netsh("show", "profiles"), "listing")
        self.assertEqual(run.call_args[0][0], ["netsh", "wlan", "show", "profiles"])
        self.assertNotIn("shell", run.call_args[1])
        with mock.patch("subprocess.run", side_effect=OSError):
            self.fails(lambda: world._netsh("show", "profiles"), "Wi-Fi")


def fake_yt_dlp(info=None, error=None, created="Some Title [abc123].mp4", predicted="Some Title [abc123].mp4"):
    module, utils = ModuleType("yt_dlp"), ModuleType("yt_dlp.utils")

    class DownloadError(Exception):
        pass

    utils.DownloadError = DownloadError
    utils.match_filter_func = lambda expression: ("filter", expression)
    module.utils, module.seen = utils, {}

    class YoutubeDL:
        def __init__(self, options):
            module.seen["options"] = options
            self.folder = world.Path(options["outtmpl"]).parent

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            module.seen["url"] = url
            if error:
                raise DownloadError(error)
            if info is not None:
                (self.folder / created).write_bytes(b"x" * 3 * 2 ** 20)
            return info

        def prepare_filename(self, _info):
            return str(self.folder / predicted)

    module.YoutubeDL = YoutubeDL
    return module, {"yt_dlp": module, "yt_dlp.utils": utils}


class YouTubeDownloadTests(ToolCase):
    VIDEO = {"id": "abc123", "title": "Some Title"}

    def test_only_youtube_links_are_accepted(self):
        module, modules = fake_yt_dlp(info=self.VIDEO)
        with mock.patch.dict(sys.modules, modules):
            for link in ("https://evil.com/watch?v=1", "ftp://youtube.com/x", "https://youtube.com.evil.com/watch?v=1",
                         "youtube.com/watch?v=1", "file:///C:/video.mp4", ""):
                self.fails(lambda: T.download_youtube_video(url=link), "YouTube links")
        self.assertNotIn("url", module.seen)

    def test_a_video_is_downloaded_into_the_youtube_folder(self):
        module, modules = fake_yt_dlp(info=self.VIDEO)
        with mock.patch.dict(sys.modules, modules):
            text = T.download_youtube_video(url=" https://youtu.be/abc123 ")
        self.assertEqual(text, "Downloaded 'Some Title' (3.0 MB) into the YouTube downloads folder.")
        self.assertTrue((self.db / "Downloads" / "YouTube" / "Some Title [abc123].mp4").exists())
        options = module.seen["options"]
        self.assertEqual(module.seen["url"], "https://youtu.be/abc123")
        self.assertEqual(options["format"], "best[ext=mp4]/best")             # one file, so no ffmpeg is needed
        self.assertTrue(options["noplaylist"])
        self.assertEqual(options["match_filter"], ("filter", "duration <= 7200"))

    def test_audio_only(self):
        module, modules = fake_yt_dlp(info=self.VIDEO)
        with mock.patch.dict(sys.modules, modules):
            T.download_youtube_video(url="https://www.youtube.com/watch?v=abc123", audio_only=True)
        self.assertIn("bestaudio", module.seen["options"]["format"])

    def test_a_video_over_two_hours_is_skipped(self):
        _, modules = fake_yt_dlp(info=None)
        with mock.patch.dict(sys.modules, modules):
            self.fails(lambda: T.download_youtube_video(url="https://youtu.be/long"), "longer than two hours")

    def test_the_file_is_found_even_if_its_name_was_predicted_differently(self):
        _, modules = fake_yt_dlp(info=self.VIDEO, created="Other name [abc123].mp4", predicted="Missing.mp4")
        with mock.patch.dict(sys.modules, modules):
            self.assertIn("Downloaded 'Some Title'", T.download_youtube_video(url="https://youtu.be/abc123"))

    def test_youtubes_refusals_are_translated_into_plain_words(self):
        _, modules = fake_yt_dlp(error="\x1b[0;31mERROR:\x1b[0m [youtube] abc123: Sign in to confirm you're not a bot")
        with mock.patch.dict(sys.modules, modules):
            message = self.fails(lambda: T.download_youtube_video(url="https://youtu.be/abc123"),
                                 "Sign in to confirm", "Updating yt-dlp")
        self.assertNotIn("\x1b", message)
        self.assertNotIn("ERROR:", message)

    def test_a_missing_library_is_explained(self):
        with mock.patch.dict(sys.modules, {"yt_dlp": None}):
            self.fails(lambda: T.download_youtube_video(url="https://youtu.be/abc123"), "pip install yt-dlp")


GAMES = [
    {"title": "Warframe", "genre": "Shooter", "platform": "PC (Windows)", "publisher": "Digital Extremes",
     "release_date": "2013-03-25", "short_description": "A cooperative  free-to-play third person shooter.",
     "freetogame_profile_url": "https://www.freetogame.com/warframe", "game_url": "https://www.freetogame.com/open/warframe"},
    {"title": "Valorant", "genre": "Shooter", "platform": "PC (Windows)", "publisher": "Riot Games",
     "release_date": "2020-06-02", "short_description": "A 5v5 tactical shooter.",
     "freetogame_profile_url": "https://www.freetogame.com/valorant", "game_url": "https://www.freetogame.com/open/valorant"},
    {"title": "Crystal Of Atlan", "genre": "MMORPG", "platform": "PC (Windows)", "publisher": "Skystone Games",
     "release_date": "bad date", "short_description": "A magicpunk MMORPG",
     "freetogame_profile_url": "https://www.freetogame.com/crystal-of-atlan", "game_url": "https://www.freetogame.com/open/atlan"},
]


class GameTests(ToolCase):
    def setUp(self):
        super().setUp()
        self.http.on("freetogame.com/api/games", FakeResponse(GAMES))

    def test_a_game_is_found_by_name_and_its_page_opened(self):
        self.assertEqual(T.lookup_free_game(title="WARFRAME"),
                         "Warframe is a free Shooter game for PC (Windows), published by Digital Extremes and released in "
                         "March 2013. A cooperative free-to-play third person shooter. I opened its page.")
        self.assertEqual(self.opened, ["https://www.freetogame.com/warframe"])

    def test_part_of_a_name_or_a_small_typo_still_finds_it(self):
        self.assertIn("Valorant is a free", T.lookup_free_game(title="valo"))
        self.assertIn("Warframe is a free", T.lookup_free_game(title="warframr"))

    def test_an_unreadable_release_date_does_not_break_the_answer(self):
        self.assertIn("released in an unknown date", T.lookup_free_game(title="atlan"))

    def test_an_unknown_game_is_reported(self):
        self.fails(lambda: T.lookup_free_game(title="zzzzzz"), "couldn't find a free game called zzzzzz")

    def test_no_name_means_a_surprise(self):
        with mock.patch.object(world.random, "choice", return_value=GAMES[1]):
            self.assertTrue(T.lookup_free_game().startswith("Here's a free game you could try: Valorant"))

    def test_the_game_list_is_downloaded_once(self):
        T.lookup_free_game(title="warframe")
        T.lookup_free_game(title="valorant")
        self.assertEqual(len(self.http.calls), 1)

    def test_an_empty_list_is_an_error(self):
        self.http.routes = [("freetogame.com/api/games", FakeResponse([]))]
        _common.clear_cache()
        self.fails(lambda: T.lookup_free_game(title="warframe"), "came back empty")


class MinecraftTests(ToolCase):
    def test_an_online_server(self):
        self.http.on("mcsrvstat.us/3/play.cubecraft.net", FakeResponse({
            "online": True, "ip": "193.105.184.96", "players": {"online": 596, "max": 5000}, "version": "We support: 1.20-1.21",
            "motd": {"clean": ["   \u25c0 CubeCraft Games [EU] \u25b6  ", "  HALLOWEEN EVENT: HUNT, MAPS &amp; HUB!  "]}}))
        self.assertEqual(T.lookup_minecraft_server(host=" Play.CubeCraft.net "),
                         "play.cubecraft.net is online with 596 of 5,000 players, version We support: 1.20-1.21. "
                         "Its message of the day: CubeCraft Games [EU] HALLOWEEN EVENT: HUNT, MAPS & HUB!.")

    def test_a_server_that_exists_but_does_not_answer(self):
        self.http.on("mcsrvstat.us", FakeResponse({"online": False, "ip": "172.65.197.160"}))
        self.assertIn("exists, but no Minecraft server answered", T.lookup_minecraft_server(host="mc.hypixel.net"))

    def test_an_address_that_does_not_exist(self):
        self.http.on("mcsrvstat.us", FakeResponse({"online": False, "ip": "127.0.0.1"}))
        self.assertIn("couldn't find any server called no-such.example", T.lookup_minecraft_server(host="no-such.example"))

    def test_only_server_addresses_are_accepted(self):
        for host in ("bad host!", "http://example.com", "a/b", "", "-leading.example"):
            self.fails(lambda: T.lookup_minecraft_server(host=host), "server address")
        self.assertEqual(self.http.calls, [])

    def test_a_port_is_allowed(self):
        self.http.on("mcsrvstat.us/3/play.example.com:25565", FakeResponse({"online": True, "players": {"online": 1, "max": 20}}))
        self.assertIn("is online with 1 of 20 players.", T.lookup_minecraft_server(host="play.example.com:25565"))


class CovidTests(ToolCase):
    WORLD = {"cases": 704753890, "todayCases": 0, "deaths": 7010681, "recovered": 675619811, "active": 22123398,
             "updated": 1792224578000}

    def test_worldwide_figures(self):
        self.http.on("covid-19/all", FakeResponse(self.WORLD))
        text = T.get_disease_outbreak_stats()
        self.assertIn("Worldwide: 704,753,890 total COVID-19 cases (0 reported today), 7,010,681 deaths, "
                      "675,619,811 recovered, 22,123,398 active.", text)
        self.assertIn("some countries no longer report daily", text)

    def test_a_country(self):
        self.http.on("covid-19/countries/United%20States", FakeResponse(dict(self.WORLD, country="USA")))
        self.assertTrue(T.get_disease_outbreak_stats(country="United States").startswith("USA: 704,753,890"))

    def test_a_partial_country_name_is_retried_loosely(self):
        self.http.on("covid-19/countries/Pakis", lambda url, params: (
            FakeResponse(dict(self.WORLD, country="Pakistan")) if params.get("strict") == "false" else FakeResponse({}, 404)))
        self.assertTrue(T.get_disease_outbreak_stats(country="Pakis").startswith("Pakistan:"))
        self.assertEqual([p.get("strict") for _, p in self.http.calls], [None, "false"])

    def test_a_loose_search_may_return_a_list(self):
        self.http.on("covid-19/countries/Pak", lambda url, params: (
            FakeResponse([dict(self.WORLD, country="Pakistan")]) if params.get("strict") == "false" else FakeResponse({}, 404)))
        self.assertTrue(T.get_disease_outbreak_stats(country="Pak").startswith("Pakistan:"))

    def test_an_unknown_country(self):
        self.http.on("covid-19/countries", FakeResponse({"message": "Country not found"}, 404))
        self.fails(lambda: T.get_disease_outbreak_stats(country="Atlantis"), "COVID-19 figures for Atlantis")

    def test_other_diseases_are_not_pretended(self):
        self.fails(lambda: T.get_disease_outbreak_stats(disease="measles"), "only have live figures for COVID-19")
        self.assertEqual(self.http.calls, [])

    def test_unreadable_figures(self):
        self.http.on("covid-19/all", FakeResponse({"message": "?"}))
        self.fails(lambda: T.get_disease_outbreak_stats(), "figures I couldn't read")


if __name__ == "__main__":
    unittest.main()
