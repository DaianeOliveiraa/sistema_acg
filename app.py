import fitz  # PyMuPDF
import re
import os
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from typing import Set, Dict, Any

app = Flask(__name__)

@app.route("/")
def home():
    return "Minha aplicação Flask está rodando no Render!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Desativa cache para arquivos estáticos
# Configuração do diretório de uploads e banco de dados
UPLOAD_FOLDER = './uploads'
DATABASE = "database.db"

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DATABASE'] = DATABASE

# Criar diretório de uploads se não existir
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Inicializar banco de dados
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(''' 
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            status TEXT DEFAULT 'Pendente',
            comment TEXT,
            categoria TEXT,
            horas_extraidas REAL,
            horas_validadas REAL,
            limite_maximo INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Definição das regras de classificação
REGRAS = [
    {"categoria": "Participar de programa de Iniciação Científica, reconhecido pela Pró-Reitoria de Pesquisa ou órgão equivalente", "keywords": ["iniciação científica", "pesquisa"], "carga_por_atividade": 50, "carga_maxima": 100},
    {"categoria": "Monitoria reconhecida pelo IFNMG", "keywords": ["monitoria"], "carga_por_atividade": 30, "carga_maxima": 100},
    {"categoria": "Cursos e Minicursos diversos como: idiomas, comunicação e expressão, informática, tecnologias, dentre outros. Projetos e oficinas temáticas", "keywords": ["conclusão do curso", "curso", "minicurso", "idiomas", "informática", "projeto", "oficina"], "carga_por_atividade": 10, "carga_maxima": 100},
    {"categoria": "Trabalho apresentado em eventos científicos ou publicações de trabalhos em periódicos especializados, anais de congressos e similares", "keywords": ["evento científico", "congresso", "publicação", "anais"], "carga_por_atividade": 40, "carga_maxima": 100},
    {"categoria": "Particpação em seminários (exceto SIC), encontros estudantis,jornadas científicas e semanas acadêmicas, reconhecidos por instituições de Ensino Superior", "keywords": ["SEMAD", "mostra", ",encontro de iniciação" "seminário", "jornada científica", "semana acadêmica"], "carga_por_atividade": 10, "carga_maxima": 100},
    {"categoria": "Particpação em projetos de extensão, projetos de pesquisa e tecnologia, desafio reconhecidos por instituições de Ensino Superior", "keywords": ["extensão", "Desafio", "desafio jovem empreendedor"], "carga_por_atividade": 20, "carga_maxima": 100},
    {"categoria": "Participação em congressos, fóruns e simpósios reconhecidos por instituições de Ensino Superior", "keywords": ["congresso", "simpósio", "fórum"], "carga_por_atividade": 20, "carga_maxima": 100},
    {"categoria": "Participação em palestras e conferências", "keywords": ["palestra", "conferência", "mesa-redonda", "êxito"], "carga_por_atividade": 4, "carga_maxima": 50},
    {"categoria": "Organização de eventos acadêmicos, científicos ou culturais como membro de Comissão Central ou Principal", "keywords": ["organização", "evento", "acadêmico", "científico", "cultural","comissão centtral"], "carga_por_atividade": 40, "carga_maxima": 100},
    {"categoria": "Organização de Eventos Acadêmicos, científicos ou culturais como membro de Comissão Secundária, subcomissões ou de apoio", "keywords": ["organização", "evento", "acadêmico", "científico", "cultural", "apoio"], "carga_por_atividade": 20, "carga_maxima": 100}, 
    {"categoria": "Participação em visitas técnicas programadas", "keywords": ["visita técnica", "visita"], "carga_por_atividade": 10, "carga_maxima": 100},
    {"categoria": "Comissões e representação estudantil Institucional, diretórios acadêmicos, empresa júnior e grupos de estudos institucionalizados", "keywords": ["comissão", "representação", "estudantil", "institucional", "diretório acadêmico", "empresa júnior", "grupo de estudo"], "carga_por_atividade": 40, "carga_maxima": 100},
    {"categoria": "Participação em programa de estágio voluntário no IFNMG", "keywords": ["estágio", "voluntário"], "carga_por_atividade": 40, "carga_maxima": 100},
    {"categoria": "Trabalho na organização ou participação em campanhas de voluntariado ou programas de ação social", "keywords": ["trabalho", "organização", "campanha", "voluntariado", "ação social"], "carga_por_atividade": 10, "carga_maxima": 100},
]

horas_por_categoria = {}

# Função para extrair texto de um PDF
def extrair_texto_pdf(arquivo):
    try:
        with fitz.open(stream=arquivo.read(), filetype="pdf") as pdf:
            texto = ""
            for pagina in pdf:
                # Configuração otimizada para extração
                texto += pagina.get_text("text", flags=fitz.TEXT_PRESERVE_LIGATURES | 
                                       fitz.TEXT_PRESERVE_WHITESPACE | 
                                       fitz.TEXT_DEHYPHENATE)
            return texto.lower()  # Retorna em minúsculas para uniformização
    except Exception as e:
        raise ValueError(f"Erro ao extrair texto do PDF: {str(e)}")

# Função principal que decide qual método usar
def extrair_horas(texto):
    # Padrão para certificados do tipo "com carga horária de X hora(s)"
    match_novo_formato = re.search(
        r'com carga hor[áa]ria de (\d+)(?:[.,](\d+))?\s*(?:h|horas|hrs|hora\(s\))',
        texto,
        re.IGNORECASE
    )
    
    if match_novo_formato:
        inteiro = match_novo_formato.group(1)
        decimal = match_novo_formato.group(2) if match_novo_formato.group(2) else '0'
        if decimal != '0':
            horas = float(f"{inteiro}.{decimal}")
        else:
            horas = int(inteiro)
        return round(horas, 1)

    # Padrão 1: Formato HH:MM (ex: "2:30 horas")
    match_hm = re.search(r"(\d{1,2}):(\d{2})\s*(?:h|horas|hrs)?\b", texto, re.IGNORECASE)
    if match_hm:
        horas = int(match_hm.group(1)) + (int(match_hm.group(2)) / 60)
        return round(horas, 1)

    # Padrão 2: Formato com "hora(s)" e variações
    match_horas = re.search(
        r'(\d+)(?:[.,](\d+))?\s*(?:h|horas|hrs|hora\(s\))(?:\s*e)?\b',
        texto,
        re.IGNORECASE
    )
    
    if match_horas:
        inteiro = match_horas.group(1)
        decimal = match_horas.group(2) if match_horas.group(2) else '0'
        if decimal != '0':
            horas = float(f"{inteiro}.{decimal}")
        else:
            horas = int(inteiro)
        return round(horas, 1)

    return 0.0
    
# Função para classificar atividades
def classificar_atividade(texto, horas):
    texto = texto.replace("\n", " ")  # Remover quebras de linha
    texto = " ".join(texto.split())  # Remover espaços extras

    for regra in REGRAS:
        if any(keyword in texto.lower() for keyword in regra["keywords"]):
            categoria = regra["categoria"]
            carga_maxima = regra["carga_maxima"]
            carga_por_atividade = regra["carga_por_atividade"]

            if categoria not in horas_por_categoria:
                horas_por_categoria[categoria] = 0

            horas_disponiveis = carga_maxima - horas_por_categoria[categoria]
            horas_validadas = min(horas, carga_por_atividade, horas_disponiveis)

            horas_por_categoria[categoria] += horas_validadas

            return {
                "categoria": categoria,
                "horas_extraidas": horas,
                "horas_validadas": horas_validadas,
                "limite_maximo": carga_maxima,
                "horas_atualmente_registradas": horas_por_categoria[categoria],
                "status": "Classificado"
            }

    # Se não encontrou categoria, retorna "Pendente" para o professor classificar
    return {
        "categoria": "Desconhecida",
        "horas_extraidas": horas,
        "horas_validadas": 0,
        "limite_maximo": 0,
        "status": "Pendente"
    }

# Rota para upload de certificados
@app.route("/upload", methods=["POST"])
def upload_certificados():
    if "files" not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400

    arquivos = request.files.getlist("files")
    if not arquivos:
        return jsonify({"erro": "Nenhum arquivo selecionado"}), 400

    resultados = []
    total_horas_validadas = 0

    for arquivo in arquivos:
        
        try:
            texto_extraido = extrair_texto_pdf(arquivo)
            horas = extrair_horas(texto_extraido)
            classificacao = classificar_atividade(texto_extraido, horas)
            total_horas_validadas += classificacao["horas_validadas"]

            # Salvar o arquivo
            filename = os.path.join(UPLOAD_FOLDER, arquivo.filename)
            arquivo.save(filename)

            # Armazena no banco de dados
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO uploads (filename, status) VALUES (?, "Pendente")', (arquivo.filename,))  
            upload_id = cursor.lastrowid  # Get the id of the last inserted row
            conn.commit()
            conn.close()

            resultados.append({
                "arquivo": arquivo.filename,
                "horas_extraidas": horas,
                "classificacao": classificacao,
                "status": "Pendente"
            })
        except ValueError as e:
            return jsonify({"erro": f"Erro ao processar {arquivo.filename}: {str(e)}"}), 500

    return jsonify({
        "resultados": resultados,
        "total_horas_validadas": total_horas_validadas
    }), 200


# Rota para listar todos os arquivos enviados (modificada)
@app.route("/uploads", methods=["GET"])
def listar_arquivos():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename, status, comment, categoria, horas_extraidas, horas_validadas, limite_maximo FROM uploads")
    arquivos = cursor.fetchall()
    conn.close()

    return jsonify([{
        "id": row[0],
        "filename": row[1],
        "status": row[2],
        "comment": row[3],
        "categoria": row[4],
        "horas_extraidas": row[5],
        "horas_validadas": row[6],
        "limite_maximo": row[7]
    } for row in arquivos]), 200

# Modificar a rota de visualização de arquivos
@app.route("/uploads/<filename>", methods=["GET"])
def visualizar_arquivo(filename):
    # Desativar cache para esta rota
    response = send_from_directory(
        app.config['UPLOAD_FOLDER'], 
        filename,
        mimetype='application/pdf'
    )
    
    # Adicionar headers para evitar cache
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    return response

# Modificar a função de extração de texto para garantir que o arquivo seja fechado
def extrair_texto_pdf(arquivo):
    try:
        # Salvar a posição original do arquivo
        original_position = arquivo.tell()
        arquivo.seek(0)
        
        # Ler o conteúdo em memória
        file_content = arquivo.read()
        
        with fitz.open(stream=file_content, filetype="pdf") as pdf:
            texto = ""
            for pagina in pdf:
                texto += pagina.get_text("text", flags=fitz.TEXT_PRESERVE_LIGATURES | 
                                       fitz.TEXT_PRESERVE_WHITESPACE | 
                                       fitz.TEXT_DEHYPHENATE)
            
        # Retornar o arquivo para a posição original
        arquivo.seek(original_position)
        return texto.lower()
    except Exception as e:
        raise ValueError(f"Erro ao extrair texto do PDF: {str(e)}")

# Rota para aprovar certificado
@app.route("/aprovar_certificado", methods=["POST"])
def aprovar_certificado():
    data = request.json
    filename = data.get("filename")
    
    if not filename:
        return jsonify({"erro": "Nome do arquivo é obrigatório"}), 400

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("UPDATE uploads SET status = 'Aprovado' WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()

    return jsonify({"mensagem": f"Certificado {filename} aprovado com sucesso"}), 200

# Rota para rejeitar certificado
@app.route("/rejeitar_certificado", methods=["POST"])
def rejeitar_certificado():
    data = request.json
    filename = data.get("filename")
    motivo = data.get("motivo", "Motivo não especificado")
    
    if not filename:
        return jsonify({"erro": "Nome do arquivo é obrigatório"}), 400

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("UPDATE uploads SET status = 'Rejeitado', comment = ? WHERE filename = ?", 
                   (motivo, filename))
    conn.commit()
    conn.close()

    return jsonify({"mensagem": f"Certificado {filename} rejeitado: {motivo}"}), 200

# Rota para atualizar categoria de um certificado
@app.route("/atualizar_categoria", methods=["POST"])
def atualizar_categoria():
    data = request.json
    filename = data.get("filename")
    nova_categoria = data.get("categoria")
    horas_validadas = data.get("horas_validadas", 0)
    
    if not filename or not nova_categoria:
        return jsonify({"erro": "Nome do arquivo e categoria são obrigatórios"}), 400

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Busca o limite máximo para a nova categoria
    limite_maximo = next((regra["carga_maxima"] for regra in REGRAS if regra["categoria"] == nova_categoria), 100)
    
    cursor.execute("""
        UPDATE uploads 
        SET categoria = ?, horas_validadas = ?, limite_maximo = ?, status = 'Classificado' 
        WHERE filename = ?
    """, (nova_categoria, horas_validadas, limite_maximo, filename))
    
    conn.commit()
    conn.close()

    return jsonify({
        "mensagem": f"Categoria do certificado {filename} atualizada para {nova_categoria}",
        "horas_validadas": horas_validadas,
        "limite_maximo": limite_maximo
    }), 200

# Rota para obter categorias disponíveis
@app.route("/categorias", methods=["GET"])
def listar_categorias():
    categorias = [regra["categoria"] for regra in REGRAS]
    return jsonify(categorias), 200

# Nova rota para verificar atualizações
@app.route("/check_updates", methods=["GET"])
def check_updates():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Obter a última modificação para cada arquivo do aluno atual
    cursor.execute("""
        SELECT filename, status, comment, categoria, horas_validadas 
        FROM uploads 
        ORDER BY id DESC
    """)
    
    arquivos = cursor.fetchall()
    conn.close()
    
    return jsonify([{
        "arquivo": row[0],
        "status": row[1],
        "comment": row[2],
        "categoria": row[3],
        "horas_validadas": row[4]
    } for row in arquivos]), 200

# Rota principal (mantida igual)
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    app.run(debug=True)
