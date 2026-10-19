"""Tests for understanding a request by its parts:  python -m unittest tests.test_frames -v

The sentences are ones really said to Jarvis (speech recognition included), plus the ordinary ways of changing them.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from JarvisAdvancedBot import Frames as F  # noqa: E402


def frame(text):
    found = F.parse(text)
    return None if found is None else (found.action, tuple(sorted(found.nouns)), found.which, found.number, found.text, found.day)


class ParseTests(unittest.TestCase):
    def test_removing_a_numbered_item_in_every_way_it_is_said(self):
        for text in ("remove task 2", "can you remove the second task", "delete task number two", "please remove item 2 from my to do list",
                     "complete task 2", "i want you to delete the 2nd task", "erase task #2", "get rid of task two"):
            self.assertEqual(frame(text), ("remove", ("task",), "number", 2, "", ""), text)

    def test_the_real_sentences_that_failed(self):
        self.assertEqual(frame("can you remove the third task i am done from the to do"), ("remove", ("task",), "number", 3, "", ""))
        self.assertEqual(frame("remove the last task from the task folder"), ("remove", ("task",), "last", 0, "", ""))
        self.assertEqual(frame("delete the last tas"), ("remove", ("task",), "last", 0, "", ""))                  # "task" cut short
        self.assertEqual(frame("can you remove the last text from the list"), ("remove", ("task",), "last", 0, "", ""))   # heard as "text"
        self.assertEqual(frame("can you remove the last test from the recent"), ("remove", ("task",), "last", 0, "", ""))
        self.assertEqual(frame("remove not number 2"), ("remove", ("note",), "number", 2, "", ""))                # heard as "not"
        self.assertEqual(frame("can you remove the knot number 2"), ("remove", ("note",), "number", 2, "", ""))
        self.assertEqual(frame("can you delete all 9"), ("remove", (), "all", 0, "", ""))
        self.assertEqual(frame("can you remove all"), ("remove", (), "all", 0, "", ""))
        self.assertEqual(frame("can you clear all"), ("remove", (), "all", 0, "", ""))

    def test_last_first_and_all_for_tasks_and_notes(self):
        self.assertEqual(frame("delete the last note"), ("remove", ("note",), "last", 0, "", ""))
        self.assertEqual(frame("remove the newest note"), ("remove", ("note",), "last", 0, "", ""))
        self.assertEqual(frame("remove the first task"), ("remove", ("task",), "first", 1, "", ""))
        self.assertEqual(frame("remove the oldest note"), ("remove", ("note",), "first", 0, "", ""))
        self.assertEqual(frame("remove all my notes and tasks"), ("remove", ("note", "task"), "all", 0, "", ""))
        self.assertEqual(frame("wipe everything off my notes"), ("remove", ("note",), "all", 0, "", ""))
        self.assertEqual(frame("delete the notes"), ("remove", ("note",), "all", 0, "", ""))                       # plural: all of them
        self.assertEqual(frame("delete the note"), ("remove", ("note",), "last", 0, "", ""))

    def test_an_item_pointed_to_by_its_words(self):
        for text in ("cross off dentist", "get rid of the dentist item", "tick off the dentist task", "mark dentist as done",
                     "remove dentist from my list", "take dentist off my to do list"):
            self.assertEqual(frame(text)[:3], ("remove", frame(text)[1], "text"), text)
            self.assertEqual(frame(text)[4], "dentist", text)

    def test_a_day_can_be_named(self):
        self.assertEqual(frame("remove the last task for tomorrow")[5], "tomorrow")
        self.assertEqual(frame("remove task 2 from friday")[5], "friday")

    def test_adding_with_nothing_said_about_what_to_add_leaves_it_to_be_asked(self):
        for text, noun in (("add another task", "task"), ("can you add another note", "note"), ("please add a new task", "task"),
                           ("make one more note", "note")):
            self.assertEqual(frame(text), ("add", (noun,), "", 0, "", ""), text)
        self.assertEqual(frame("put buy milk on my list"), ("add", ("task",), "text", 0, "buy milk", ""))

    def test_a_sentence_that_only_mentions_these_words_is_not_an_instruction(self):
        for text in ("do not delete the notes", "i think the last task is hard", "why did you remove my note", "the task was removed yesterday",
                     "what is a task", "check out the weather", "hello", "make a tourist spot today", "how do i clear a cache"):
            self.assertIsNone(frame(text), text)


class NumberWordTests(unittest.TestCase):
    def test_number_words_become_digits(self):
        for words, digits in (("fifteen percent of two hundred", "15 percent of 200"), ("twelve times twelve", "12 times 12"),
                              ("two hundred and fifty plus forty five", "250 plus 45"), ("one thousand two hundred", "1200"),
                              ("set a timer for five minutes", "set a timer for 5 minutes"), ("a dollar in rupees", "1 dollar in rupees"),
                              ("an hour ago", "an hour ago"), ("nothing to change here", "nothing to change here")):
            self.assertEqual(F.numerals(words), digits)


class RepairTests(unittest.TestCase):
    def test_typos_and_slips_in_command_words_are_put_right(self):
        for wrong, right in (("show all available wifi networds", "show all available wifi networks"),
                             ("give me saved wifi passowrds", "give me saved wifi passwords"),
                             ("open task holder", "open task folder"), ("open the calcuator", "open the calculator"),
                             ("what is the temprature in lahore", "what is the temperature in lahore"),
                             ("take a screnshot", "take a screenshot")):
            self.assertEqual(F.repair(wrong), right)

    def test_ordinary_words_are_left_alone(self):
        for text in ("give me the clock reading", "do i need an umbrella in lahore today", "what is the weather", "tell me about the roman empire"):
            self.assertIsNone(F.repair(text), text)


if __name__ == "__main__":
    unittest.main()
