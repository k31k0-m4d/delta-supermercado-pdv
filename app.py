from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
import os
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = 'delta123'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Inicializa o banco de dados
def init_db():
    conn = sqlite3.connect('delta.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS produtos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT,
                    preco REAL,
                    tipo TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS vendas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT,
                    preco REAL,
                    tipo TEXT,
                    quantidade INTEGER,
                    data TEXT DEFAULT CURRENT_TIMESTAMP,
                    cupom_id INTEGER
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS cupons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT
                )''')
    conn.commit()
    conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')
        if usuario == 'liziane' and senha == '1234':
            session['logado'] = True
            return redirect(url_for('home'))
        else:
            flash('Usuário ou senha incorretos!')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logado', None)
    return redirect(url_for('login'))

@app.before_request
def proteger_rotas():
    rotas_livres = ['login', 'static']
    if request.endpoint not in rotas_livres and not session.get('logado'):
        return redirect(url_for('login'))

@app.route('/')
def index():
    return redirect(url_for('home'))

@app.route('/home')
def home():
    conn = sqlite3.connect('delta.db')
    ultimas = conn.execute("SELECT * FROM vendas ORDER BY data DESC LIMIT 5").fetchall()

    hoje = datetime.now()
    dias = [(hoje - timedelta(days=i)).strftime('%d/%m') for i in range(6, -1, -1)]
    totais = [0 for _ in dias]

    rows = conn.execute("SELECT data, preco, quantidade FROM vendas WHERE date(data) >= date('now', '-7 days')").fetchall()
    por_dia = defaultdict(float)
    for data, preco, quantidade in rows:
        dia = datetime.strptime(data, '%Y-%m-%d %H:%M:%S').strftime('%d/%m')
        por_dia[dia] += preco * quantidade

    totais = [por_dia.get(d, 0) for d in dias]
    conn.close()

    return render_template('home.html', ultimas=ultimas, dias=dias, totais=totais)


@app.route('/importar', methods=['POST'])
def importar():
    file = request.files['file']
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        df = pd.read_excel(filepath)
        conn = sqlite3.connect('delta.db')
        for _, row in df.iterrows():
            conn.execute('INSERT INTO produtos (nome, preco, tipo) VALUES (?, ?, ?)',
                         (row['NOME'], row['PREÇO'], row['TIPO']))
        conn.commit()
        conn.close()
        flash('Produtos importados com sucesso!')
    return redirect(url_for('home'))

@app.route('/pdv', methods=['GET'])
def pdv():
    conn = sqlite3.connect('delta.db')
    todos_produtos = conn.execute("SELECT * FROM produtos").fetchall()
    conn.close()

    carrinho = session.get('carrinho', [])
    for i in range(len(carrinho)):
        carrinho[i] = list(carrinho[i])
        if len(carrinho[i]) == 2:
            carrinho[i].append(1)

    session['carrinho'] = carrinho
    total = sum(item[1] * item[2] for item in carrinho)

    return render_template('pdv.html', todos_produtos=todos_produtos, carrinho=carrinho, total=total)

@app.route('/adicionar_carrinho', methods=['POST'])
def adicionar_carrinho():
    produto_id = request.form.get('id')
    conn = sqlite3.connect('delta.db')
    produto = conn.execute('SELECT nome, preco FROM produtos WHERE id = ?', (produto_id,)).fetchone()
    conn.close()

    if produto:
        carrinho = session.get('carrinho', [])
        nome, preco = produto
        encontrado = False

        for i in carrinho:
            if i[0] == nome:
                i[2] += 1
                encontrado = True
                break

        if not encontrado:
            carrinho.append([nome, preco, 1])

        session['carrinho'] = carrinho

    return redirect(url_for('pdv'))

@app.route('/remover_item', methods=['POST'])
def remover_item():
    nome = request.form.get('nome')
    carrinho = session.get('carrinho', [])
    carrinho = [item for item in carrinho if item[0] != nome]
    session['carrinho'] = carrinho
    return redirect(url_for('pdv'))

@app.route('/atualizar_quantidade', methods=['POST'])
def atualizar_quantidade():
    nome = request.form.get('nome')
    acao = request.form.get('acao')
    carrinho = session.get('carrinho', [])

    for item in carrinho:
        if item[0] == nome:
            if acao == 'adicionar':
                item[2] += 1
            elif acao == 'subtrair':
                item[2] -= 1
            break

    carrinho = [i for i in carrinho if i[2] > 0]
    session['carrinho'] = carrinho
    return redirect(url_for('pdv'))

@app.route('/finalizar_venda', methods=['POST'])
def finalizar_venda():
    carrinho = session.get('carrinho', [])
    conn = sqlite3.connect('delta.db')
    cursor = conn.cursor()

    cursor.execute('INSERT INTO cupons (data) VALUES (?)', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
    cupom_id = cursor.lastrowid

    for item in carrinho:
        nome, preco, quantidade = item
        tipo = cursor.execute('SELECT tipo FROM produtos WHERE nome = ?', (nome,)).fetchone()
        tipo = tipo[0] if tipo else 'N/A'
        cursor.execute('INSERT INTO vendas (nome, preco, tipo, quantidade, cupom_id) VALUES (?, ?, ?, ?, ?)',
                       (nome, preco, tipo, quantidade, cupom_id))

    conn.commit()
    conn.close()
    session['ultima_venda'] = carrinho
    session['carrinho'] = []
    return redirect(url_for('recibo'))

@app.route('/recibo')
def recibo():
    carrinho = session.get('ultima_venda', [])
    total = sum(item[1] * item[2] for item in carrinho)
    data = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    return render_template('recibo.html', carrinho=carrinho, total=total, data=data)

@app.route('/vendas')
def vendas():
    conn = sqlite3.connect('delta.db')
    cursor = conn.cursor()

    # Busca todos os cupons
    rows = cursor.execute("SELECT id, data FROM cupons ORDER BY data DESC").fetchall()

    cupons = []
    for row in rows:
        cupom_id = row[0]
        data = row[1]

        # Soma o total do cupom com base nos produtos relacionados
        total_row = cursor.execute("SELECT SUM(preco * quantidade) FROM vendas WHERE cupom_id = ?", (cupom_id,)).fetchone()
        total = total_row[0] if total_row[0] else 0.0

        cupons.append({
            'id': cupom_id,
            'data': data,
            'total': total
        })

    conn.close()
    return render_template('vendas.html', cupons=cupons)

@app.route('/cupom/<int:cupom_id>')
def cupom(cupom_id):
    conn = sqlite3.connect('delta.db')
    cursor = conn.cursor()
    rows = cursor.execute("SELECT nome, preco, quantidade FROM vendas WHERE cupom_id = ?", (cupom_id,)).fetchall()
    conn.close()

    produtos = [{'nome': r[0], 'preco': r[1], 'qtd': r[2]} for r in rows]
    total = sum(p['preco'] * p['qtd'] for p in produtos)

    return render_template('cupom.html', cupom_id=cupom_id, produtos=produtos, total=total)




    conn.close()

    return render_template('home.html', ultimas=ultimas, dias=dias, totais=totais)

@app.route('/excluir_venda', methods=['POST'])
def excluir_venda():
    venda_id = request.form.get('id')
    conn = sqlite3.connect('delta.db')
    conn.execute('DELETE FROM vendas WHERE id = ?', (venda_id,))
    conn.commit()
    conn.close()
    flash('Venda excluída com sucesso!')
    return redirect(url_for('vendas'))

@app.route('/produtos')
def produtos():
    conn = sqlite3.connect('delta.db')
    produtos = conn.execute("SELECT * FROM produtos").fetchall()
    conn.close()
    return render_template('produtos.html', produtos=produtos)


@app.route('/adicionar_produto', methods=['POST'])
def adicionar_produto():
    nome = request.form.get('nome')
    preco = request.form.get('preco')
    tipo = request.form.get('tipo')

    try:
        preco = float(preco)
    except ValueError:
        flash('Preço inválido.')
        return redirect(url_for('produtos'))

    conn = sqlite3.connect('delta.db')
    conn.execute('INSERT INTO produtos (nome, preco, tipo) VALUES (?, ?, ?)', (nome, preco, tipo))
    conn.commit()
    conn.close()

    flash('Produto adicionado com sucesso!')
    return redirect(url_for('produtos'))

@app.route('/cupom/<int:cupom_id>')
def ver_cupom(cupom_id):
    conn = sqlite3.connect('delta.db')
    cursor = conn.cursor()

    # Pega os dados do cupom
    cursor.execute("SELECT data FROM cupons WHERE id = ?", (cupom_id,))
    resultado = cursor.fetchone()
    if not resultado:
        conn.close()
        return "Cupom não encontrado", 404

    data = resultado[0]

    # Pega os produtos relacionados ao cupom
    cursor.execute("SELECT nome, preco, quantidade FROM vendas WHERE cupom_id = ?", (cupom_id,))
    itens = cursor.fetchall()
    conn.close()

    total = sum(preco * qtd for _, preco, qtd in itens)

    return render_template('cupom_detalhes.html', cupom_id=cupom_id, data=data, itens=itens, total=total)




if __name__ == '__main__':
    init_db()
    app.run(debug=True)
