from config import NASA_API_KEY
from config import BASE_DIR
from MainCode import Speak
from PIL import Image
import requests
import os


def NasaNews(Date):
    api = NASA_API_KEY
    Speak("Extracting Data From Nasa . ")
    Url = f"https://api.nasa.gov/planetary/apod?api_key={api}"
    Params = {'date': str(Date)}
    r = requests.get(Url, params=Params)
    Data = r.json()
    Info = Data['explanation']
    Title = Data['title']
    Image_Url = Data['url']
    Image_r = requests.get(Image_Url)
    FileName = str(Date) + '.jpg'
    with open(FileName, 'wb') as f:
        f.write(Image_r.content)
    Path_1 = f"{BASE_DIR}\\" + str(FileName)
    Path_2 = f"{BASE_DIR}\\DataBase\\NasaDataBase\\" + str(FileName)
    os.rename(Path_1, Path_2)
    img = Image.open(Path_2)
    img.show()
    Speak(f"Title : {Title}")
    Speak(f"According To Nasa : {Info}")
    

def MarsImage():
    api = NASA_API_KEY
    name = 'curiosity'
    date = '2020-12-3'
    Api_ = str(api)
    url = f"https://api.nasa.gov/mars-photos/api/v1/rovers/{name}/photos?earth_date={date}&api_key={Api_}"
    r = requests.get(url)
    Data = r.json()
    Photos = Data['photos'][:12]
    try:
        for index, photo in enumerate(Photos):
            camera = photo['camera']
            rover = photo['rover']
            rover_name = rover['name']
            camera_name = camera['name']
            full_camera_name = camera['full_name']
            date_of_photo = photo['earth_date']
            img_url = photo['img_src']
            p = requests.get(img_url)
            img = f'{index}.jpg'
            with open(img, 'wb') as file:
                file.write(p.content)
            Path_1 = f"{BASE_DIR}\\" + str(img)
            Path_2 = f"{BASE_DIR}\\DataBase\\NasaDataBase\\Mars Images\\" + \
                str(img)
            os.rename(Path_1, Path_2)
            os.startfile(Path_2)
            Speak(f"This Image Was Captured With : {full_camera_name}")
            Speak(f"This Image Was Captured On : {date_of_photo}")
    except Exception as e:
        Speak("There is An Error!")
        print(e)


def SolarBodies(body):
    url = "https://api.le-systeme-solaire.net/rest/bodies/"
    r = requests.get(url)
    Data = r.json()
    bodies = Data["bodies"]
    number = len(bodies)
    url2 = f"https://api.le-systeme-solaire.net/rest/bodies/{body}"
    rr = requests.get(url2)
    data = rr.json()
    mass = data['mass']['massValue']
    vol = data['vol']['volValue']
    gravity = data['gravity']
    den = data['density']
    esp = data['escape']
    engName = data["englishName"]
    sideRot = data["sideralRotation"]
    sideOrbit = data["sideralOrbit"]
    MeanRadius = data["meanRadius"]
    Eccentricity = data["eccentricity"]
    ArgPeriapsis = data["argPeriapsis"]
    MainAnomaly = data["mainAnomaly"]
    Aphelion = data["aphelion"]
    Perihelion = data['perihelion']
    SemimajorAxis = data["semimajorAxis"]

    Speak(f"Number of bodies in the universe are {number}")
    Speak(f"Mass of {body} is {mass}")
    Speak(f"Volume of {body} is {vol}")
    Speak(f"Density of {body} is {den}")
    Speak(f"Gravity on {body} is {gravity}")
    Speak(f"Velocity of {body} is {esp}")
    Speak(f"Side rotation of {body} is {sideRot}")
    Speak(f"Side orbit of {body} is {sideOrbit}")
    Speak(f"Mean radius of {body} is {MeanRadius}")
    Speak(f"Eccentricity of {body} is {Eccentricity}")
    Speak(f"ArgPeriapsis of {body} is {ArgPeriapsis}")
    Speak(f"MainAnomaly of {body} is {MainAnomaly}")
    Speak(f"Aphelion of {body} is {Aphelion}")
    Speak(f"Perihelion of {body} is {Perihelion}")
    Speak(f"Semi major axis of {body} is {SemimajorAxis}")


def Astro(start_date,end_date):
    Api_Key = NASA_API_KEY
    url = f"https://api.nasa.gov/neo/rest/v1/feed?start_date={start_date}&end_date={end_date}&api_key={Api_Key}"
    r = requests.get(url)
    Data = r.json()
    Total_Astro = Data['element_count']
    # print(Data)
    # print(Total_Astro)
    neo = Data['near_earth_objects']
    Speak(f"Total Astroid Between {start_date} and {end_date} are: {Total_Astro}")
    Speak("Extacted Data For Those Astroids Are Listed Below .")
    for body in neo[start_date]:
        id = body['id']
        name = body['name']
        absolute = body['absolute_magnitude_h']
        print(id,name,absolute)


def IssTracker():
    url = "http://api.open-notify.org/iss-now.json"
    r = requests.get(url)
    Data = r.json()
    print(Data)
    dt = Data['timestamp']
    lat = Data['iss_position']['latitude']
    lon = Data['iss_position']['longitude']

    Speak("Sir I have tracked the International Space Station Unit...")
    Speak(f"Now the current position of the International Space Station on latitude is {lat}")
    Speak(f"and the current position on longitude is {lon}")
    Speak(f"The current date and time taken to change its position is: {dt}")
