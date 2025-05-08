"""
Protótipo de IA fraca para Telegram Bot
Características:
- Integração com API do Telegram usando python-telegram-bot
- Aprendizado incremental baseado nas interações com usuários
- Armazenamento e processamento de histórico de conversas
- Sistema de feedback para melhoria contínua
"""

import os
import json
import logging
import re
import random
import time
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from unidecode import unidecode
import sqlite3
import requests

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Diretórios para armazenamento de dados
DADOS_DIR = "dados_ia"
CONVERSAS_DIR = os.path.join(DADOS_DIR, "conversas")
CONHECIMENTO_FILE = os.path.join(DADOS_DIR, "conhecimento.json")
RESPOSTAS_FILE = os.path.join(DADOS_DIR, "respostas_aprendidas.json")
FEEDBACK_FILE = os.path.join(DADOS_DIR, "feedback.json")
ESTATISTICAS_FILE = os.path.join(DADOS_DIR, "estatisticas.json")

# Criação de diretórios necessários
os.makedirs(CONVERSAS_DIR, exist_ok=True)

# Classe principal da IA
class IASimples:
    def __init__(self):
        self.conn = sqlite3.connect("dados_ia.db")
        self._criar_tabelas()
        
        self.conhecimento = self._carregar_json(CONHECIMENTO_FILE, {})
        self.respostas = self._carregar_json(RESPOSTAS_FILE, {})
        self.feedback = self._carregar_json(FEEDBACK_FILE, {})
        self.estatisticas = self._carregar_json(ESTATISTICAS_FILE, 
            {"interacoes": 0, "feedback_positivo": 0, "feedback_negativo": 0, "ultima_atualizacao": ""})
        
        # Respostas padrão para quando a IA não souber responder
        self.respostas_padrao = [
            "Ainda estou aprendendo sobre isso.",
            "Não tenho conhecimento suficiente para responder.",
            "Poderia me ensinar mais sobre esse assunto?",
            "Não entendi bem. Pode explicar de outra forma?",
            "Estou processando esse tema ainda, me desculpe."
        ]

    def _criar_tabelas(self):
        """Cria as tabelas necessárias no banco de dados"""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS conhecimento (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pergunta TEXT UNIQUE,
                    resposta TEXT,
                    data_adicao TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS estatisticas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interacoes INTEGER,
                    feedback_positivo INTEGER,
                    feedback_negativo INTEGER,
                    ultima_atualizacao TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mensagem_id INTEGER,
                    user_id INTEGER,
                    tipo_feedback TEXT
                )
            """)

    def _carregar_json(self, arquivo, padrao=None):
        """Carrega dados de um arquivo JSON ou retorna o valor padrão"""
        try:
            if os.path.exists(arquivo):
                with open(arquivo, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return padrao if padrao is not None else {}
        except Exception as e:
            logger.error(f"Erro ao carregar arquivo {arquivo}: {e}")
            return padrao if padrao is not None else {}

    def _salvar_json(self, dados, arquivo):
        """Salva dados em um arquivo JSON"""
        try:
            with open(arquivo, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo {arquivo}: {e}")
            return False

    def buscar_na_wikipedia(self, pergunta):
        """Busca uma resposta resumida na Wikipedia em português."""
        try:
            url = f"https://pt.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(pergunta)}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if "extract" in data and data["extract"]:
                    return data["extract"]
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar na Wikipedia: {e}")
            return None

    def processar_mensagem(self, texto, user_id):
        """Processa a mensagem recebida e retorna uma resposta"""
        # Normaliza o texto para busca
        texto_normalizado = unidecode(texto.lower().strip())
        
        # Registra a interação
        self.estatisticas["interacoes"] += 1
        self.estatisticas["ultima_atualizacao"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._salvar_json(self.estatisticas, ESTATISTICAS_FILE)
        
        # Busca por palavras-chave no conhecimento existente
        resposta = None
        max_correspondencia = 0
        
        # Procura a melhor correspondência no conhecimento existente
        for padrao, info in self.conhecimento.items():
            palavras_padrao = set(re.findall(r'\w+', padrao.lower()))
            palavras_mensagem = set(re.findall(r'\w+', texto_normalizado))
            
            # Calcula a intersecção entre as palavras
            correspondencia = len(palavras_padrao.intersection(palavras_mensagem))
            
            # Se tem palavras em comum e é melhor que a atual
            if correspondencia > 0 and correspondencia > max_correspondencia:
                max_correspondencia = correspondencia
                resposta = info["resposta"]
        
        # Se não encontrou no conhecimento, procura nas respostas aprendidas
        if not resposta:
            for padrao, respostas_possiveis in self.respostas.items():
                if padrao in texto_normalizado or texto_normalizado in padrao:
                    # Seleciona a resposta com maior pontuação
                    if respostas_possiveis:
                        resposta = max(respostas_possiveis, key=lambda x: x["pontuacao"])["texto"]
                        break
        
        # Se ainda não encontrou resposta, tenta buscar na Wikipedia
        if not resposta:
            resposta = self.buscar_na_wikipedia(texto)
        
        # Se ainda não encontrou, usa uma resposta padrão
        if not resposta:
            resposta = random.choice(self.respostas_padrao)
        
        # Registra a conversa para aprendizado futuro
        self._registrar_conversa(texto, resposta, user_id)
        
        logger.info(f"Processando mensagem de user_id={user_id}: {texto}")
        return resposta

    def adicionar_conhecimento(self, pergunta, resposta):
        """Adiciona novo conhecimento à base"""
        self.conhecimento[pergunta] = {
            "resposta": resposta,
            "data_adicao": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self._salvar_json(self.conhecimento, CONHECIMENTO_FILE)

    def _registrar_conversa(self, pergunta, resposta, user_id):
        """Registra a conversa para análise e aprendizado futuro"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        arquivo = os.path.join(CONVERSAS_DIR, f"conversa_{user_id}_{timestamp}.json")
        
        dados = {
            "user_id": user_id,
            "timestamp": timestamp,
            "pergunta": pergunta,
            "resposta": resposta
        }
        
        self._salvar_json(dados, arquivo)

    def registrar_feedback(self, mensagem_id, user_id, tipo_feedback):
        """Registra feedback (positivo ou negativo) sobre uma resposta"""
        with self.conn:
            self.conn.execute("""
                INSERT INTO feedback (mensagem_id, user_id, tipo_feedback)
                VALUES (?, ?, ?)
            """, (mensagem_id, user_id, tipo_feedback))

    def _aprender_com_feedback(self, mensagem_id, tipo_feedback):
        """Aprende com o feedback recebido"""
        # Recupera a conversa relacionada ao feedback
        arquivo_conversa = None
        for arquivo in os.listdir(CONVERSAS_DIR):
            if mensagem_id in arquivo:
                arquivo_conversa = os.path.join(CONVERSAS_DIR, arquivo)
                break
        
        if not arquivo_conversa:
            return
            
        # Carrega a conversa
        try:
            with open(arquivo_conversa, 'r', encoding='utf-8') as f:
                conversa = json.load(f)
                
            pergunta = conversa.get("pergunta", "").lower().strip()
            resposta = conversa.get("resposta", "")
            
            # Atualiza as respostas aprendidas
            if pergunta not in self.respostas:
                self.respostas[pergunta] = []
            
            # Verifica se a resposta já existe
            resposta_existente = False
            for item in self.respostas[pergunta]:
                if item["texto"] == resposta:
                    # Atualiza a pontuação
                    if tipo_feedback == "positivo":
                        item["pontuacao"] += 1
                    else:
                        item["pontuacao"] -= 0.5
                    resposta_existente = True
                    break
            
            # Se não existe, adiciona
            if not resposta_existente:
                pontuacao = 1 if tipo_feedback == "positivo" else -0.5
                self.respostas[pergunta].append({
                    "texto": resposta,
                    "pontuacao": pontuacao
                })
                
            # Salva as alterações
            self._salvar_json(self.respostas, RESPOSTAS_FILE)
            
        except Exception as e:
            logger.error(f"Erro ao processar feedback: {e}")

# Funções para o bot do Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia mensagem quando o comando /start é enviado."""
    await update.message.reply_text(
        "Olá! Sou uma IA em treinamento. 😊\n"
        "Converse comigo para me ajudar a aprender!\n"
        "Use /ajuda para ver os comandos disponíveis."
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envia mensagem de ajuda."""
    await update.message.reply_text(
        "Comandos disponíveis:\n"
        "/start - Inicia a conversa\n"
        "/ajuda - Exibe esta mensagem\n"
        "/ensinar pergunta | resposta - Ensina algo novo\n"
        "/estatisticas - Mostra minhas estatísticas de aprendizado\n\n"
        "Qualquer outra mensagem será processada como uma pergunta."
    )

async def ensinar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite ao usuário ensinar algo à IA"""
    mensagem = update.message.text.replace("/ensinar ", "")
    
    # Verifica se a mensagem tem o formato correto
    if "|" not in mensagem:
        await update.message.reply_text(
            "Formato incorreto. Use: /ensinar pergunta | resposta"
        )
        return
    
    # Separa a pergunta e a resposta
    partes = mensagem.split("|", 1)
    pergunta = partes[0].strip()
    resposta = partes[1].strip()
    
    # Adiciona o conhecimento
    ia.adicionar_conhecimento(pergunta, resposta)
    
    await update.message.reply_text(
        f"Obrigado! Aprendi que quando me perguntarem sobre '{pergunta}', "
        f"devo responder: '{resposta}'"
    )

async def estatisticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra estatísticas da IA"""
    stats = ia.estatisticas
    
    mensagem = (
        f"📊 *Estatísticas de Aprendizado*\n\n"
        f"Total de interações: {stats['interacoes']}\n"
        f"Feedback positivo: {stats['feedback_positivo']}\n"
        f"Feedback negativo: {stats['feedback_negativo']}\n"
        f"Última atualização: {stats['ultima_atualizacao']}\n\n"
        f"Base de conhecimento: {len(ia.conhecimento)} itens\n"
        f"Respostas aprendidas: {len(ia.respostas)} padrões"
    )
    
    await update.message.reply_text(mensagem, parse_mode='Markdown')

# Função principal para processar mensagens do usuário
async def processar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text

    # Processa a mensagem e obtém resposta da IA
    resposta = ia.processar_mensagem(texto, user_id)

    # Envia a resposta com botões de feedback
    keyboard = [
        [
            InlineKeyboardButton("👍", callback_data=f"feedback_positivo_{update.message.message_id}"),
            InlineKeyboardButton("👎", callback_data=f"feedback_negativo_{update.message.message_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(resposta, reply_markup=reply_markup)

async def processar_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o feedback dos botões"""
    query = update.callback_query
    await query.answer()
    
    partes = query.data.split("_")
    if len(partes) >= 3:
        tipo_feedback = partes[1]  # positivo ou negativo
        mensagem_id = partes[2]
        user_id = update.effective_user.id
        
        # Registra o feedback
        ia.registrar_feedback(mensagem_id, user_id, tipo_feedback)
        
        # Atualiza a mensagem para mostrar que o feedback foi registrado
        await query.edit_message_reply_markup(reply_markup=None)
        
        mensagem = "Obrigado pelo feedback! Isso me ajuda a melhorar. 😊" if tipo_feedback == "positivo" else "Obrigado pelo feedback. Vou tentar melhorar! 🤔"
        await query.edit_message_text(text=f"{query.message.text}\n\n{mensagem}")

def main():
    """Inicia o bot"""
    try:
        # Cria a aplicação do bot
        application = Application.builder().token(token).build()

        # Adiciona os handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("ajuda", ajuda))
        application.add_handler(CommandHandler("ensinar", ensinar))
        application.add_handler(CommandHandler("estatisticas", estatisticas))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, processar_mensagem))
        application.add_handler(CallbackQueryHandler(processar_feedback))

        # Inicia o bot
        application.run_polling()
    except Exception as e:
        logger.error(f"Erro ao iniciar o bot: {e}")

# Inicia a IA e o bot
if __name__ == "__main__":
    # Carrega variáveis de ambiente do arquivo .env
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise ValueError("O token do bot não foi encontrado. Certifique-se de configurá-lo no arquivo .env.")
    
    ia = IASimples()
    print("Iniciando o bot da IA...")
    main()