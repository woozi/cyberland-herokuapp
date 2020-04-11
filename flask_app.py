import requests
import re
from flask import Flask, escape, request, redirect
from collections import namedtuple
import concurrent.futures
import threading
import time

cache_lock = threading.Lock()

CacheEntry = namedtuple('CacheEntry', ['posts', 'time'])

cache = {}

def get_posts(board_name, thread_id="", recent_first=True):
    print("get_posts", thread_id)
    r = requests.get(f'https://cyberland.club/{board_name}/?thread={thread_id}&num=999999999999999')
    print(r.url, r.text)
    posts = r.json()
    posts = sorted(posts, key=lambda x: int(x['id']), reverse=recent_first)
    return posts

def get_posts_for_board(board_name):
    posts = get_posts(board_name)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {}
        for post in posts:
            future = executor.submit(get_posts, board_name, thread_id=post['id'], recent_first=False)
            futures[future] = post

        while futures:
            completed, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in completed:
                replies = future.result()
                post = futures[future]
                post['replies'] = []
                for reply in replies:
                    if post['id'] == reply['id']:
                        continue
                    post['replies'].append(reply)
                    new_future = executor.submit(get_posts, board_name, thread_id=reply['id'], recent_first=False)
                    futures[new_future] = reply
                del futures[future]

    return posts

def get_posts_cacheable(board_name):
    CACHE_STALE_SECS = 20
    with cache_lock:
        if not board_name in cache or cache[board_name].time - time.time() > CACHE_STALE_SECS:
            posts = get_posts_for_board(board_name)
            cache[board_name] = CacheEntry(posts=posts, time=time.time())
        return cache[board_name].posts

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


    posts = get_posts_cacheable(name)
    
    def render_post(post):
        nonlocal page
        page += '<div class="post">'
        page += '<div class="content">'
        page += f'<a href="javascript:quote({post["id"]})" id="p{post["id"]}">#{post["id"]}</a><br>'
        page += str(escape(post['content']))
        page += '</div>'
        page += '<div class="replies">'
        if 'replies' in post:
            for reply in post['replies']:
                render_post(reply)
        page += '</div>'
        page += '</div>'
        
    for post in posts:
        render_post(post)

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
    with cache_lock:
        del cache[name]
    return redirect(f'/{name}')

if __name__ == '__main__':
    app.run(debug=True)