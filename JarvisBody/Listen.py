import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import speech_recognition as sr
from microphone import Microphone
from deep_translator import GoogleTranslator

def Listen():
    r = sr.Recognizer()
    
    with Microphone() as source:
        print(": Listening.....")
        r.pause_threshold = 1
        audio = r.listen(source,0,8)
    
    try:
        print(": Recognizing.....")
        query = r.recognize_google(audio,language='en-pk')
    
    except:
        return ""
    
    query = str(query).lower()
    return query

def TranslateUrduToEnglish(Text):
    line = str(Text)
    data = GoogleTranslator(source="auto", target="en").translate(line)
    print(f"You: {data}.")

def MicExe():
    query = Listen()
    Trans = TranslateUrduToEnglish(query)
    return Trans

