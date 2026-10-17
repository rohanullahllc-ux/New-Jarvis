from MainCode import Speak
from MainCode import Listen
import requests
import webbrowser
import pause


def GetLandPadInfo(id):
    Url2 = f"https://api.spacexdata.com/v3/landpads/{id}"
    r = requests.get(Url2)
    Data = r.json()
    # print(Data)
    LandPadId = Data["id"]
    Full_name = Data["full_name"]
    Location = Data["location"]
    PlaceName = Location["name"]
    Region = Location["region"]
    latitude = Location["latitude"]
    longitude = Location["longitude"]
    landing_type = Data["landing_type"]
    attempted_landings = Data["attempted_landings"]
    successful_landings = Data["successful_landings"]
    GetWikiInfo = Data["wikipedia"]
    LandingDetails = Data["details"]
    Speak(f"Sir the id of this landpad is {LandPadId}")
    Speak(f"Sir full name of this landpad is {Full_name}")
    Speak(f"This landing was done in {PlaceName}, and region {Region}")
    Speak(f"Sir the position of this landpad in latitude is {latitude}")
    Speak(f"and sir the position of this landpad in longitude is {longitude}")
    Speak(f"Sir the landing type of this landpad is {landing_type}")
    Speak(
       f"Sir totall attempted landings by this landpad is {attempted_landings}")
    Speak(
        f"and sir totall successful landings by this landpad is {successful_landings}")
    Speak("According to SpaceX")
    Speak(LandingDetails)
    Speak("Sir you can get more information from wikipedia about this landpad")
    webbrowser.open(GetWikiInfo)


def SpaceXMission(Mid):
    Url = f"https://api.spacexdata.com/v3/missions/{Mid}"
    r = requests.get(Url)
    Data = r.json()
    Name = Data["mission_name"]
    Id = Data["mission_id"]
    manufacturers = Data["manufacturers"]
    description = Data["description"]
    wikiInfo = Data["wikipedia"]
    website = Data["website"]
    Speak(f"Sir id of this mission is {Id}")
    Speak(f"and sir name of this mission is {Name}")
    Speak(f"According to SpaceX")
    Speak(description)
    Speak("Sir you can get more information from wikipedia")
    webbrowser.open(wikiInfo)
    pause.seconds(2)
    webbrowser.open(website)


def SpaceXInfo():
    Url = "https://api.spacexdata.com/v3/info"
    r = requests.get(Url)
    Data = r.json()
    CompanyName = Data["name"]
    Founder = Data["founder"]
    ceo = Data["ceo"]
    FoundedOn = Data["founded"]
    employees = Data["employees"]
    cto = Data["cto"]
    coo = Data["coo"]
    cto_propulsion = Data["cto_propulsion"]
    valuation = Data["valuation"]
    headquaters = Data["headquarters"]
    address = headquaters["address"]
    city = headquaters["city"]
    state = headquaters["state"]
    links = Data["links"]
    website = links["website"]
    twitter = links["twitter"]
    elon_twitter = links["elon_twitter"]
    Summary = Data["summary"]
    Speak(f"Name of the company is {CompanyName}")
    Speak(f"Founder of the company is {Founder}")
    Speak(f"CEO of the company is {ceo}")
    Speak(f"CTO of the company is {cto}")
    Speak(f"COO of the company is {coo}")
    Speak(f"This company was founded on {FoundedOn}")
    Speak(f"Total employees in this company are {employees}")
    Speak(f"CTO propulsion of {CompanyName} is {cto_propulsion}")
    Speak(f"This company is situated in {city}, state {state}, {address}")
    Speak(f"Accordind to {CompanyName}")
    Speak(Summary)
    Speak("Checking for its social media links")
    pause.seconds(5)
    webbrowser.open(website)
    pause.seconds(2)
    Speak(f"This is the official website of {CompanyName}")
    webbrowser.open(twitter)
    pause.seconds(2)
    Speak(f"This is the official twitter account of {CompanyName}")
    webbrowser.open(elon_twitter)
    pause.seconds(2)
    Speak(f"and this is the official twitter account of {Founder}")


def RoadsterInfo():
    Url = "https://api.spacexdata.com/v3/roadster"
    r = requests.get(Url)
    Data = r.json()
    Name = Data["name"]
    launch_date_utc = Data["launch_date_utc"]
    launch_mass_kg = Data["launch_mass_kg"]
    launch_mass_lbs = Data["launch_mass_lbs"]
    orbit_type = Data["orbit_type"]
    apoapsis_au = Data["apoapsis_au"]
    periapsis_au = Data["periapsis_au"]
    semi_major_axis_au = Data["semi_major_axis_au"]
    eccentricity = Data["eccentricity"]
    inclination = Data["inclination"]
    period_days = Data["period_days"]
    speed_kph = Data["speed_kph"]
    speed_mph = Data["speed_mph"]
    earth_distance_km = Data["earth_distance_km"]
    earth_distance_mi = Data["earth_distance_mi"]
    mars_distance_km = Data["mars_distance_km"]
    mars_distance_mi = Data["mars_distance_mi"]
    flickr_images = Data["flickr_images"]
    img1 = flickr_images[0]
    img2 = flickr_images[1]
    img3 = flickr_images[2]
    img4 = flickr_images[3]
    WikiInfo = Data["wikipedia"]
    Video = Data["video"]
    Details = Data["details"]
    Speak(f"The name of the roadster is {Name}")
    Speak(f"The launch date is {launch_date_utc}")
    Speak(f"The mass of the roadster in kilogram is {launch_mass_kg}")
    Speak(f"The mass of the roadster in lbs is {launch_mass_lbs}")
    Speak(f"The orbital type of this roadster is {orbit_type}")
    Speak(f"The apoapsis of this roadster is {apoapsis_au}")
    Speak(f"The periapsis of this roadster is {periapsis_au}")
    Speak(f"The semi major axis of this roadster is {semi_major_axis_au}")
    Speak(f"The eccentricity of this roadster is {eccentricity}")
    Speak(f"The inclination of this roadster is {inclination}")
    Speak(f"The speed of this roadster in kilometer per hour is {speed_kph}")
    Speak(f"The speed of this roadster in miles per hour is {speed_mph}")
    Speak(
        f"The distance of roadster from earth in kilometer is {earth_distance_km}")
    Speak(
        f"The distance of roadster from earth in miles is {earth_distance_mi}")
    Speak(
        f"The distance of roadster from mars in kilometer is {mars_distance_km}")
    Speak(f"The distance of roadster from mars in miles is {mars_distance_mi}")
    Speak("According to SpaceX")
    Speak(Details)
    webbrowser.open(WikiInfo)
    pause.seconds(2)
    Speak(f"For more information read this wikipedia article on {Name}")
    Speak("Sir searching for relevent images")
    pause.seconds(5)
    Speak("I have found some images for you")
    Speak("Here you go with images")
    Speak("Image 1")
    webbrowser.open(img1)
    pause.seconds(3)
    Speak("Image 2")
    webbrowser.open(img2)
    pause.seconds(3)
    Speak("Image 3")
    webbrowser.open(img3)
    pause.seconds(3)
    Speak("Image 4")
    webbrowser.open(img4)
    Speak(f"Should I play a relevent video about the {Name}")
    v = input("Enter y(YES) n(NO)")
    if "y" in v:
        Speak("Searching for a video")
        webbrowser.open(Video)
        pause.seconds(2)
        Speak("I hope you liked this information")
    else:
        Speak("All right sir")


def HistoricalEevents(Id):
    Url = f"https://api.spacexdata.com/v3/history/{Id}"
    r = requests.get(Url)
    Data = r.json()
    print(Data)
    Title = Data["title"]
    Details = Data["details"]
    links = Data["links"]
    article = links["article"]
    wikiInfo = links["wikipedia"]
    Speak("Title:")
    Speak(Title)
    Speak("According to SpaceX")
    Speak(Details)
    webbrowser.open(article)
    pause.seconds(3)
    Speak("You can see this website for more information")
    pause.seconds(5)


def StarLink():
    Url = "https://api.spacexdata.com/v4/starlink/5eed7714096e590006985634"
    req = requests.get(Url)
    Data = req.json()
    # print(Data)
    spaceTrack = Data["spaceTrack"]
    CREATION_DATE = spaceTrack["CREATION_DATE"]
    OBJECT_NAME = spaceTrack["OBJECT_NAME"]
    OBJECT_ID = spaceTrack["OBJECT_ID"]
    CENTER_NAME = spaceTrack["CENTER_NAME"]
    TIME_SYSTEM = spaceTrack["TIME_SYSTEM"]
    MEAN_ELEMENT_THEORY = spaceTrack["MEAN_ELEMENT_THEORY"]
    MEAN_MOTION = spaceTrack["MEAN_MOTION"]
    ECCENTRICITY = spaceTrack["ECCENTRICITY"]
    INCLINATION = spaceTrack["INCLINATION"]
    ARG_OF_PERICENTER = spaceTrack["ARG_OF_PERICENTER"]
    MEAN_ANOMALY = spaceTrack["MEAN_ANOMALY"]
    CLASSIFICATION_TYPE = spaceTrack["CLASSIFICATION_TYPE"]
    ELEMENT_SET_NO = spaceTrack["ELEMENT_SET_NO"]
    BSTAR = spaceTrack["BSTAR"]
    MEAN_MOTION_DOT = spaceTrack["MEAN_MOTION_DOT"]
    MEAN_MOTION_DDOT = spaceTrack["MEAN_MOTION_DDOT"]
    SEMIMAJOR_AXIS = spaceTrack["SEMIMAJOR_AXIS"]
    PERIOD = spaceTrack["PERIOD"]
    APOAPSIS = spaceTrack["APOAPSIS"]
    PERIAPSIS = spaceTrack["PERIAPSIS"]
    OBJECT_TYPE = spaceTrack["OBJECT_TYPE"]
    RCS_SIZE = spaceTrack["RCS_SIZE"]
    COUNTRY_CODE = spaceTrack["COUNTRY_CODE"]
    LAUNCH_DATE = spaceTrack["LAUNCH_DATE"]
    SITE = spaceTrack["SITE"]
    DECAY_DATE = spaceTrack["DECAY_DATE"]
    DECAYED = spaceTrack["DECAYED"]
    FILE = spaceTrack["FILE"]
    GP_ID = spaceTrack["GP_ID"]
    TLE_LINE0 = spaceTrack["TLE_LINE0"]
    TLE_LINE1 = spaceTrack["TLE_LINE1"]
    TLE_LINE2 = spaceTrack["TLE_LINE2"]
    print(TLE_LINE2)
    print(spaceTrack)

