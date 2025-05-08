import unittest
from iabot import IASimples

class TestIASimples(unittest.TestCase):
    def setUp(self):
        self.ia = IASimples()

    def test_adicionar_conhecimento(self):
        self.ia.adicionar_conhecimento("O que é Python?", "Python é uma linguagem de programação.")
        resposta = self.ia.conhecimento.get("O que é Python?")
        self.assertIsNotNone(resposta)
        self.assertEqual(resposta["resposta"], "Python é uma linguagem de programação.")