from config import BASE_DIR
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QTimer, QTime, QDate, Qt
from PyQt5.QtGui import QMovie
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from JarvisUI import Ui_MainWindow
from sound_player import playsound
from MainCode import Speak
from MainCode import Listen
import webbrowser
import MainCode

class MainThread(QThread):
    
    def __init__(self):
        super(MainThread,self).__init__()
    

    def run(self):
        MainCode.taskExe()

StartExe = MainThread()

class GUI_Start(QMainWindow):

    def __init__(self):
        super().__init__()

        self.GUI = Ui_MainWindow()
        self.GUI.setupUi(self)

        self.GUI.pushButton_9.clicked.connect(self.Open_YouTube)
        self.GUI.pushButton_10.clicked.connect(self.Open_FaceBook)
        self.GUI.pushButton.clicked.connect(self.StartTask)
        self.GUI.pushButton_3.clicked.connect(self.Music_start)
        self.GUI.pushButton_2.clicked.connect(self.close)
        # self.GUI.pushButton_4.clicked.connect(self.StopMusic)
        self.GUI.pushButton_5.clicked.connect(self.GoogleSearch)
        self.GUI.pushButton_6.clicked.connect(self.YouTubeSearch)
        self.GUI.pushButton_7.clicked.connect(self.Open_Insta)
        self.GUI.pushButton_8.clicked.connect(self.Open_Google)


    def Music_start(self):
        playsound(rf"{BASE_DIR}\DataBase\Sounds\Iron Man Music.mp3", block=False)
    

    def Open_Insta(self):
        webbrowser.open("https://www.instagram.com/")
    

    def Open_FaceBook(self):
        webbrowser.open("https://www.facebook.com/")
    

    def Open_Google(self):
        webbrowser.open("https://www.google.com/")
    
    
    def Open_YouTube(self):
        webbrowser.open("https://www.youtube.com/")
    

    def GoogleSearch(self):
        from pywikihow import search_wikihow
        import wikipedia
        Speak("What do you want to search on google...")
        Query = Listen()
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


    def YouTubeSearch(self):
        import pywhatkit
        Speak("What do you want to search on youtube...")
        term = Listen()
        result = "https://www.youtube.com/results?search_query=" + term
        webbrowser.open(result)
        Speak("This Is What I Found For Your Search .")
        pywhatkit.playonyt(term)
        Speak("This May Also Help You Sir .")


    def StartTask(self):
        self.GUI.label2 = QtGui.QMovie(f"{BASE_DIR.as_posix()}/G.U.I Material/ExtraGui/initial.gif")
        self.GUI.label_2.setMovie(self.GUI.label2)
        self.GUI.label2.start()
        
        self.GUI.label3 = QtGui.QMovie(f"{BASE_DIR.as_posix()}/G.U.I Material/ExtraGui/Earth.gif")
        self.GUI.label_5.setMovie(self.GUI.label3)
        self.GUI.label3.start()
        
        self.GUI.label4 = QtGui.QMovie(f"{BASE_DIR.as_posix()}/G.U.I Material/ExtraGui/jarvis-4.gif")
        self.GUI.label_7.setMovie(self.GUI.label4)
        self.GUI.label4.start()
        
        self.GUI.label5 = QtGui.QMovie(f"{BASE_DIR.as_posix()}/G.U.I Material/B.G/Iron_Template_1.gif")
        self.GUI.label_9.setMovie(self.GUI.label5)
        self.GUI.label5.start()
        
        self.GUI.label6 = QtGui.QMovie(f"{BASE_DIR.as_posix()}/G.U.I Material/ExtraGui/live.gif")
        self.GUI.label_11.setMovie(self.GUI.label6)
        self.GUI.label6.start()
        
        self.GUI.label7 = QtGui.QMovie(f"{BASE_DIR.as_posix()}/G.U.I Material/ExtraGui/Code_Template.gif")
        self.GUI.label_12.setMovie(self.GUI.label7)
        self.GUI.label7.start()

        timer = QTimer(self)
        timer.timeout.connect(self.ShowTime)
        timer.start(999)
        
        StartExe.start()
    

    def ShowTime(self):
        t_ime = QTime.currentTime()
        time = t_ime.toString()
        d_ate = QDate.currentDate()
        date = d_ate.toString()
        label_time = "Current Time: " + time
        label_date = "Current Date: " + date

        self.GUI.textBrowser_2.setText(label_time)
        self.GUI.textBrowser.setText(label_date)



if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    MainWindow = GUI_Start()
    MainWindow.show()
    sys.exit(app.exec_())
