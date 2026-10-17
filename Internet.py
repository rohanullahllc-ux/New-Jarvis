from config import BASE_DIR, EMAIL_ADDRESS, EMAIL_PASSWORD, RAPIDAPI_KEY
from geopy.distance import great_circle
from geopy.geocoders import Nominatim
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pywikihow import search_wikihow
from MainCode import Speak
from MainCode import Listen
import subprocess
import smtplib
import bs4
from requests import get
import geocoder
import requests
import wikipedia
import webbrowser as web
import speech_recognition as sr
import keyboard
import pyautogui
import pause
import os


def My_Location():

    op = "https://www.google.com/maps/place/Regi+Model+Town,+Peshawar,+Khyber+Pakhtunkhwa/data=!4m2!3m1!1s0x38d91190684dcbbd:0x29dc2f197eb30b0e?sa=X&ved=2ahUKEwjeg7yv-br0AhXtqJUCHVkrAoQQ8gF6BAgDEAE"

    Speak("Checking....")
    web.open(op)
    ip_add = get('https://api.ipify.org').text
    url = 'https://get.geojs.io/v1/ip/geo/' + ip_add + '.json'
    geo_q = get(url)
    geo_d = geo_q.json()
    state = geo_d['city']
    country = geo_d['country']
    Speak(f"Sir , You Are Now In {state , country} .")


def GoogleMaps(Place):
    Url_Place = "https://www.google.com/maps/place/" + str(Place)
    geolocator = Nominatim(user_agent="myGeocoder")
    location = geolocator.geocode(Place, addressdetails=True)
    target_latlon = location.latitude, location.longitude
    web.open(url=Url_Place)
    location = location.raw['address']
    target = {'city': location.get('city', ''),
              'state': location.get('state', ''),
              'country': location.get('country', '')}
    current_loca = geocoder.ip('me')
    current_latlon = current_loca.latlng
    distance = str(great_circle(current_latlon, target_latlon))
    distance = str(distance.split(' ', 1)[0])
    distance = round(float(distance), 2)
    Speak(target)
    Speak(f"Sir , {Place} iS {distance} Kilometre Away From Your Location . ")


def GoogleSearch(term):
    query = term.replace("jarvis","")
    query = query.replace("google search ","")
    query = query.replace(" ","")
    query = query.replace("what do you mean by","")

    writeab = str(query)

    oooooo = open(f'{BASE_DIR}\\Data.txt','a')
    oooooo.write(writeab)
    oooooo.close()

    Query = str(term)
    import pywhatkit
    pywhatkit.search(Query)
    os.startfile(rf"{BASE_DIR}\DataBase\ExtraPrograms\start.py")
    
    try:
        if 'how to' in Query or "How to" in Query:   
            max_result = 1
            how_to_func = search_wikihow(query=Query,max_results=max_result)
            assert len(how_to_func) == 1
            how_to_func[0].print()
            Speak(how_to_func[0].summary)

        else:
            search = wikipedia.summary(Query,6)
            Speak(f": According To Your Search : {search}")
    except Exception as e:
        print(e)
        Speak("No speakable data available...")


def YouTubeSearch(term):
    result = "https://www.youtube.com/results?search_query=" + term
    web.open(result)
    Speak("This Is What I Found For Your Search .")
    import pywhatkit
    pywhatkit.playonyt(term)
    Speak("This May Also Help You Sir .")


def CoronaVirus(Country):
    countries = str(Country).replace(" ", "")
    url = f"https://www.worldometers.info/coronavirus/country/{countries}/"
    result = requests.get(url)
    soups = bs4.BeautifulSoup(result.text, 'lxml')
    corona = soups.find_all('div', class_='maincounter-number')
    Data = []
    for case in corona:
        span = case.find('span')
        Data.append(span.string)
    cases, Death, recovored = Data
    Speak(f"Total cases in {Country} are {cases}")
    Speak(f"Total deaths in {Country} are {Death}")
    Speak(f"Total recovered in {Country} are {recovored}")


def CoronaVirusDetailed(country_name,iso):
    url = f"https://vaccovid-coronavirus-vaccine-and-treatment-tracker.p.rapidapi.com/api/npm-covid-data/country-report-iso-based/{country_name}/{iso}"

    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "vaccovid-coronavirus-vaccine-and-treatment-tracker.p.rapidapi.com"
    }

    req = requests.get(url, headers=headers)
    Data = req.json()
    Dict = Data[0]
    Rank = Dict["rank"]
    Country = Dict["Country"]
    Continent = Dict["Continent"]
    Infection_Risk = Dict["Infection_Risk"]
    Case_Fatality_Rate = Dict["Case_Fatality_Rate"]
    Test_Percentage = Dict["Test_Percentage"]
    Recovery_Proporation = Dict["Recovery_Proporation"]
    TotalCases = Dict["TotalCases"]
    NewCases = Dict["NewCases"]
    TotalDeaths = Dict["TotalDeaths"]
    NewDeaths = Dict["NewDeaths"]
    TotalRecovered = Dict["TotalRecovered"]
    NewRecovered = Dict["NewRecovered"]
    ActiveCases = Dict["ActiveCases"]
    TotalTests = Dict["TotalTests"]
    Population = Dict["Population"]
    Serious_Critical = Dict["Serious_Critical"]
    TotCases_1M_Pop = Dict["TotCases_1M_Pop"]


def WifiPassSender():
    if not (EMAIL_ADDRESS and EMAIL_PASSWORD):
        Speak("Email is not configured.")
        return
    def send_mail(email, password, to, message):
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(email, password)
        server.sendmail(email, to, message)
        server.quit()
    
    Speak("Enter the email on which you want to recieve wifi passwords...")
    email = input("[+] Enter Email on which you want to recieve WIFI passwords: ")
    sender = EMAIL_ADDRESS
    password = EMAIL_PASSWORD

    listi = []
    data = subprocess.check_output(['netsh', 'wlan', 'show',
                                    'profiles']).decode('utf-8').split('\n')
    profiles = [i.split(":")[1][1:-1] for i in data if "All User Profile" in i]
    for i in profiles:
        results = subprocess.check_output(
            ['netsh', 'wlan', 'show', 'profile', i,
            'key=clear']).decode('utf-8').split('\n')
        results = [b.split(":")[1][1:-1] for b in results if "Key Content" in b]
        try:
            listi.append(("{:<30}|  {:<}".format(i, results[0])))
        except IndexError:
            listi.append("{:<30}|  {:<}".format(i, ""))

    res = ""
    for msg in listi:
        res = res + msg + "\n"
    # print(res)
    try:
        send_mail(sender, password, email, res)
        Speak("Email successfully sended\n")
        web.open("https://mail.google.com/mail/u/0/#inbox")
    except smtplib.SMTPAuthenticationError as e:
        print(e)
        print("[+] Incorrect Email or Password")


def SendEmail():
    if not (EMAIL_ADDRESS and EMAIL_PASSWORD):
        Speak("Email is not configured. Add EMAIL_ADDRESS and EMAIL_PASSWORD to the dot env file.")
        return
    Speak("Ok sir please fill in the some information...")
    email = EMAIL_ADDRESS
    password = EMAIL_PASSWORD
    Speak("Sir please type the reciever email...")
    # Whom you are sending the message to
    send_to_email = input("Enter the reciever: ")
    Speak("okay sir, what is the subject for this email")
    sub = input("Write the subject for this email: ")
    subject = sub   # The Subject in the email
    Speak("and sir, what is the message for this email")
    mes = input("Write the message for this email: ")
    message = mes  # The message in email
    Speak("Sir do you want to send with an attachment...")
    att = Listen()
    if "yes" in att:
        Speak("sir please enter the correct path of the file into the shell")
        # The File attachment in the email
        file_location = input("please enter the path here:\n")
        Speak("please wait,i am sending email now")
        msg = MIMEMultipart()
        msg['From'] = email
        msg['To'] = send_to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        # Setup the attachment
        filename = os.path.basename(file_location)
        attachment = open(file_location, "rb")
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', "attachment; filename= %s" % filename)
        # Attach the attachment to the MIMEMultipart object
        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email, password)
        text = msg.as_string()
        server.sendmail(email, send_to_email, text)
        server.quit()
        Speak("email has been sended successfully sir...")

    else:
        email1 = email
        password1 = password
        send_to_email1 = send_to_email
        subject1 = sub
        contentii = mes
        message1 = contentii
        msg1 = MIMEMultipart()
        msg1['From'] = email1
        msg1['To'] = send_to_email1
        msg1['Subject'] = subject1
        msg1.attach(MIMEText(contentii, 'plain'))
        server1 = smtplib.SMTP('smtp.gmail.com', 587)
        server1.starttls()
        server1.login(email1, password1)
        server1.sendmail(email1, send_to_email1, msg1.as_string())
        server1.quit()
        Speak("Email has been sended successfully sir...")


