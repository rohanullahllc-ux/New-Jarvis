import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from config import BASE_DIR
import os
from GoogleImageScrapper.GoogleImageScrapper import GoogleImageScraper
import pyautogui

def GoogleImage():
    oo = open(f'{BASE_DIR}\\Data.txt','rt')
    query = str(oo.read())
    oo.close()
    print(query)
    pppp = open(f'{BASE_DIR}\\Data.txt','r+')
    pppp.truncate(0)
    pppp.close()

    webdriver = rf"{BASE_DIR}\\DataBase\\webdriver\\chromedriver.exe"
    photos = f"{BASE_DIR}\\DataBase\\GooglePhotos\\"

    search_keys = [f"{query}"]
    number = 10
    head = False
    max = (1000,1000)
    min = (0,0)

    for search_key in search_keys:
        image_search = GoogleImageScraper(webdriver,photos,search_keys,number,head,min,max)
        image_url = image_search.find_image_urls()
        image_search.save_images(image_url)

    os.startfile(photos)

GoogleImage()
