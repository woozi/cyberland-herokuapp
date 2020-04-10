import requests
import re
from flask import Flask, escape, request, redirect
from collections import namedtuple

Board = namedtuple('Board', ['name', 'title'])

boards = [Board('t', 'technology'), Board('n', 'news'), Board('o', 'off-topic')]

def board_by_name(name):
    for board in boards:
        if board.name == name:
            return board

app = Flask(__name__)

@app.route('/')
@app.route('/<name>')
def route_board(name=None):
    active_board = board_by_name(name)

    page = '''
    <html>
    <head>
    <style>
    body {
        color: lime;
        background: black;
        font-family: monospace;
    }
    a {
        color: lime!important;
    }
    a:hover, a.active {
        color: black!important;
        background: lime!important;
    }
    textarea {
        width: 500px;
        height: 200px;
        background: black;
        color: lime;
        border: 1px solid lime;
    }
    input[type=submit] {
        border: 1px solid lime;
        background: black;
        color: lime;
        font-family: monospace;
        font-size: 12pt;
        padding: 10px;
        width: 500px;
    }
    input[type=submit]:hover {
        cursor: pointer;
        color: black;
        background: lime;
        border: 1px solid black;
    }
    .post {

    }
    .content {
        padding: 10px;
        margin-bottom: 10px;
        border-left: 1px solid lime;
    }
    .replies {
        padding-left: 10px;
        border-left: 1px solid green;
    }
    </style>
    </head>
    <body>
    '''
    menu = []
    for board in boards:
        if board == active_board:
            menu.append(f'<a class="active" href="/{board.name}">/{board.name}/ - {board.title}</a></b>')
        else:
            menu.append(f'<a href="/{board.name}">/{board.name}/ - {board.title}</a>')
    page += ' | '.join(menu)

    if not active_board:
        return page

    page += f'<h1>/{active_board.name}/ - {active_board.title}</h1>'

    page += f'''
    <form method="post" action="{name}/post">
    <textarea name="content"></textarea><br>
    <input type="submit">
    </form>
    <br>
    '''

    def get_posts(thread_id="", recent_first=True):
        print("get_posts", thread_id)
        r = requests.get(f'https://cyberland.club/{name}/?thread={thread_id}&num=999999999999999')
        posts = r.json()
        posts = sorted(posts, key=lambda x: int(x['id']), reverse=recent_first)
        return posts

    posts = get_posts()

    def post_by_id(id):
        print('post by id: ', id)
        for post in posts:
            if post['id'] == id:
                return post
    
    def process_post(post):
        print('process_post', post)
        nonlocal page
        page += '<div class="post">'
        page += '<div class="content">'
        page += f'<a href="javascript:quote({post["id"]})" id="p{post["id"]}">#{post["id"]}</a><br>'
        page += str(escape(post['content']))
        page += '</div>'
        replies = get_posts(post['id'], recent_first=False)
        page += '<div class="replies">'
        for reply in replies:
            if reply['id'] != post['id']:
                process_post(reply)
        page += '</div>'
        page += '</div>'
        
    for post in posts:
        process_post(post)

    page += r'''
    <script type="text/javascript">
    function quote(id) {
        let textarea = document.querySelector('textarea');
        let lines = textarea.value.split("\n");
        if (lines[0].match(/>>\d+/))
            lines.shift();
        lines.unshift(">>" + id);
        textarea.value = lines.join("\n");
    }
    </script>
    '''
    page += '</body>'
    page += '</html>'
    return page

@app.route('/<name>/post', methods=['POST'])
def route_post(name):
    board = board_by_name(name)
    if not board:
        print('no board')
        return redirect('/')
    content = request.form.get('content', None)
    if not content:
        print('no content')
        return redirect(f'/{name}')
    lines = content.split('\n', 1)
    m = re.match('>>(\d+)', lines[0])
    reply_to = "0"
    if m:
        reply_to = m.group(1)
        content = lines[1]
    data = { 'content': content, 'replyTo': reply_to }
    r = requests.post(f'https://cyberland.club/{name}/', data=data)
    print('posted')
    print(data)
    print(r.status_code, r.text)
    return redirect(f'/{name}')

if __name__ == '__main__':
    app.run(debug=True)