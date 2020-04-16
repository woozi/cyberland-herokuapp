import requests
import re
from flask import Flask, escape, request, redirect, get_flashed_messages, flash
from collections import namedtuple
import concurrent.futures
import threading
import time
from ansi import ansi_8bit_colors
from PIL import Image
from image_to_ansi import image_to_ansi

class BackendError(Exception):
    def __init__(self, response):
        super().__init__()
        self.response = response

cache_lock = threading.Lock()

CacheEntry = namedtuple('CacheEntry', ['posts', 'time'])

cache = {}


def get_all_posts(backend_url, board_name, recent_first=True):
    r = requests.get(f'{backend_url}/{board_name}/?num=999999999999999')
    try:
        posts = r.json()
    except:
        raise BackendError(r)
    return posts

def get_posts(board_name, thread_id="0", recent_first=True):
    print("get_posts", thread_id)
    r = requests.get(f'{API_BACKEND}/{board_name}/?thread={thread_id}&num=999999999999999')
    print(r.url)
    try:
        posts = r.json()
    except:
        raise BackendError(r)

    return posts

def max_id(post):
    if post['replies']:
        return max(
            max_id(reply) for reply in post['replies']
        )
    return int(post['id'])

def sort_replies(posts):
    for post in posts:
        post['replies'] = sorted(post['replies'], key=lambda x: int(x['id']))
        sort_replies(post['replies'])

def sort_ops_by_bump(posts):
    return sorted(posts, key=lambda p: max_id(p), reverse=True)

def sort_posts(posts):
    for post in posts:
        post['replies'] = sort_posts(post['replies'])
    posts = sorted(posts, key=lambda x: max_id(x), reverse=True)
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
                try:
                    replies = future.result()
                except:
                    print('cannot get replies for ', post)
                    replies = []

                post = futures[future]
                post['replies'] = []
                for reply in replies:
                    if post['id'] == reply['id']:
                        continue
                    post['replies'].append(reply)
                    new_future = executor.submit(get_posts, board_name, thread_id=reply['id'], recent_first=False)
                    futures[new_future] = reply
                del futures[future]



    posts = sort_ops_by_bump(posts)
    sort_replies(posts)

    return posts



def convert_ansi_to_html(content):
    new_content = []
    i = 0
    closing_stack = []
    while i < len(content):
        if content[i:i + 2] == '\033[':
            i += 2
            s = content[i:i + 20]
            if s.startswith('0m'):
                new_content.append(''.join(closing_stack))
                closing_stack = []
                i += 2
                continue
            m = re.match(r'(\d+);(\d+);(\d+);(\d+);(\d+)m', s)
            if m: # 24bit
                if m.group(1) == '38' and m.group(2) == '2':
                    new_content.append(f'<span style="color:rgb({m.group(3)},{m.group(4)},{m.group(5)}">')
                    closing_stack.append('</span>')
                elif m.group(1) == '48' and m.group(2) == '2':
                    new_content.append(f'<span style="background:rgb({m.group(3)},{m.group(4)},{m.group(5)}">')
                    closing_stack.append('</span>')
                i += len(m.group(0))
            else:
                m = re.match(r'(\d+);(\d+);(\d+)m', s)
                if m: # bit
                    if m.group(1) == '38' and m.group(2) == '5':
                        color = ansi_8bit_colors.get(m.group(3))
                        if color:
                            new_content.append(f'<span style="color:{color}">')
                            closing_stack.append('</span>')
                            i += len(m.group(0))
                    elif m.group(1) == '48' and m.group(2) == '5':
                        color = ansi_8bit_colors.get(m.group(3))
                        if color:
                            new_content.append(f'<span style="background:{color}">')
                            closing_stack.append('</span>')
                            i += len(m.group(0))

        else:
            new_content.append(content[i])
            i += 1
    new_content.append(''.join(closing_stack))
    return ''.join(new_content)


def get_posts_for_board_simple(backend, board_name):
    flat_posts = get_all_posts(backend.url, board_name)
    posts = []
    posts_lookup = { }
    for post in flat_posts:
        post['id'] = int(post['id'])
        post['replyTo'] = int(post['replyTo']) if post['replyTo'] else 0
        post['replies'] = []
        posts_lookup[post['id']] = post
        content = post['content']
        content = str(escape(content))
        content = convert_ansi_to_html(content)
        content = make_urls_clickable(content)
        # content = content.replace('\r\n', '\n').replace('\n', '<br>')
        post['content'] = content

    for post in flat_posts:
        if post['replyTo'] == 0:
            posts.append(post)
        else:
            if post['replyTo'] in posts_lookup:
                posts_lookup[post['replyTo']]['replies'].append(post)
            else:
                print(f'missing post {post["replyTo"]}')
    
    
    #posts = sort_ops_by_bump(posts)
    #sort_replies(posts)
    posts = sort_posts(posts)


    return posts
    


def get_posts_cacheable(backend, board_name):
    CACHE_STALE_SECS = 10
    with cache_lock:
        key = backend.name + ':' + board_name
        if not key in cache or time.time() - cache[key].time > CACHE_STALE_SECS:
            posts = get_posts_for_board_simple(backend, board_name)
            cache[key] = CacheEntry(posts=posts, time=time.time())
        return cache[key].posts

class Backend(object):
    def __init__(self, name, url, title, boards):
        self.name = name
        self.url = url
        self.title = title
        self.boards = boards

class Board(object):
    def __init__(self, name, title, images=False, char_limit=80000):
        self.name = name
        self.title = title
        self.images = images
        self.char_limit = char_limit


backends = [
    Backend('cl2', 'https://cyberland2.club', 'cyberland2.club', 
        [Board('t', 'technology'), Board('n', 'news'), Board('o', 'off-topic'), Board('i', 'image', images=True, char_limit=100000)]),
    Backend('lc', 'http://landcyber.herokuapp.com', 'landcyber.herokuapp.com', 
        [Board('t', 'technology'), Board('n', 'news'), Board('o', 'off-topic'), Board('i', 'image', images=True, char_limit=50000)]),
    Backend('cldig', 'https://cyberland.digital', 'cyberland.digital', 
        [Board('t', 'technology'), Board('n', 'news'), Board('o', 'off-topic'), Board('i', 'image', images=True), Board('c', 'client tests')]),
]

def board_by_name(backend, name):
    if not backend:
        return None
    for board in backend.boards:
        if board.name == name:
            return board

def backend_by_name(name):
    for backend in backends:
        if backend.name == name:
            return backend

def make_urls_clickable(text):
    text = re.sub(r'(https?://\w+\.\w+\S*)', r'<a href="\1" target="_blank">\1</a>', text)
    return text

app = Flask(__name__)
app.secret_key = b'_5#y2L"Ffghgfhgf4Q8z\n\xec]/'

@app.route('/')
@app.route('/<backend_name>')
@app.route('/<backend_name>/')
@app.route('/<backend_name>/<name>')
@app.route('/<backend_name>/<name>/')
def route_board(backend_name=None, name=None):
    active_backend = backend_by_name(backend_name)
    active_board = board_by_name(active_backend, name)

    page = ''
    page += '''
    <html>
    <head>
    '''
    if active_board:
        page += f'<title>/{active_board.name}/ - {active_board.title} ({active_backend.title})</title>'
    elif active_backend:
        page += f'<title>{active_backend.title}</title>'
    else:
        page += f'<title>cyberland</title>'

    page += '''
    <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png">
    <link rel="manifest" href="/static/site.webmanifest">
    '''
    page += '''
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
    }
    input[type=file] {
        background: black;
        font-family: monospace;
        color: lime;
        padding: 10px;
    }
    input[type=file]::-webkit-file-upload-button {
        background: black;
        font-family: monospace;
        color: lime;
        border: 1px solid lime;
        padding: 5px;
        margin-right: 10px;
    }
    input[type=file]::-webkit-file-upload-button:hover {
        color: black;
        background: lime;
        cursor: pointer;
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
    '''
    page += '''
    </head>
    <body>
    '''
    backend_menu = []
    for backend in backends:
        if backend == active_backend:
            backend_menu.append(f'<a class="active" href="/{backend.name}/">{backend.title}</a></b>')
        else:
            backend_menu.append(f'<a href="/{backend.name}/">{backend.title}</a>')
    page += '<div class="menu">'
    page += 'backends: '
    page += '[' + '] ['.join(backend_menu) + ']'
    page += '</div>'
    if active_backend:
        board_menu = []
        for board in active_backend.boards:
            if board == active_board:
                board_menu.append(f'<a class="active" href="/{active_backend.name}/{board.name}/">/{board.name}/ - {board.title}</a></b>')
            else:
                board_menu.append(f'<a href="/{active_backend.name}/{board.name}/">/{board.name}/ - {board.title}</a>')
        page += '<div class="menu">'
        page += 'boards: '
        page += '[' + '] ['.join(board_menu) + ']'
        page += '</div>'
    
    page += '<br>'
    
    if not active_backend:
        page += '<h1>select backend</h1>'
    if active_backend and not active_board:
        page += '<h1>select board</h1>'

    for message in get_flashed_messages():
        page += f'<div><h3>{message}</h3><br>'

    if not active_board or not active_backend:
        return page

    page += f'<h2>/{active_board.name}/ - {active_board.title} @ {active_backend.title}</h2>'

    try:
        posts = get_posts_cacheable(active_backend, name)
    except BackendError as error:
        posts = []
        page += f'<h2>backend failed ({error.response.status_code})</h2>'
        page += '<div style="border: 1px solid lime; padding: 10px">'
        page += error.response.text
        page += '</div>'
        return page

    if active_board.images:
        page += f'''
        <form method="post" enctype="multipart/form-data" action="/{active_backend.name}/{active_board.name}/post">
        <textarea name="content"></textarea><br>
        <label for="file">Attach image: </label><input id="file" type="file" name="file" accept="image/png, image/jpeg"><br>
        <input type="submit">
        </form>
        <br>
        '''
    else:
        page += f'''
        <form method="post" action="/{active_backend.name}/{active_board.name}/post">
        <textarea name="content"></textarea><br>
        <input type="submit">
        </form>
        <br>
        '''


    page += '<a id="updatePosts" href="javascript:updatePosts()">[Update posts]</a><br><br>'
    page += '<div id="posts">'

    def render_collapse(posts):
        nonlocal page
        prev_post = None
        same_posts = 0
        for post in posts:
            if prev_post and prev_post['content'] == post['content'] and not post['replies']:
                same_posts += 1
                continue
            if same_posts > 0:
                page += f'<div class="post" style="color:green">({same_posts}x repeating)</div>'
            render_post(post)
            prev_post = post
            same_posts = 0
        if same_posts > 0:
            page += f'<div class="post" style="color:green">({same_posts}x repeating)</div>'
    
    def render_post(post):
        nonlocal page
        page += '<div class="post">'
        page += '<pre class="content">'
        page += f'<a href="javascript:quote({post["id"]})" id="p{post["id"]}">#{post["id"]}</a> <i>{post["time"]}</i><br>'
        if len(post['content'].split('<br>')) > 100:
            page += f'<div class="post" style="color:green">(post hidden, over 100 lines)</div>'
        else:    
            page += post['content']
        page += '</pre>'
        page += '<div class="replies">'
        if 'replies' in post:
            render_collapse(post['replies'])
        page += '</div>'
        page += '</div>'
    
 
    render_collapse(posts)

    page += "</div>"
        

    page += r'''
    <script type="text/javascript">
    function quote(id) {
        let textarea = document.querySelector("textarea");
        let lines = textarea.value.split("\n");
        if (lines[0].match(/>>\d+/))
            lines.shift();
        lines.unshift(">>" + id);
        textarea.value = lines.join("\n");
    }

    async function updatePosts() {
        let button = document.getElementById('updatePosts');
        button.innerHTML = '...';
        let req = await fetch(window.location.href);
        let text = await req.text();
        let div = document.createElement('div');
        div.innerHTML = text;
        let posts = div.querySelector('\#posts');
        if (posts) {
            let oldPosts = document.querySelector('\#posts');
            oldPosts.parentNode.replaceChild(posts, oldPosts);
        }
        button.innerHTML = '[Update posts]';
    }
    </script>
    '''
    page += '</body>'
    page += '</html>'
    return page

@app.route('/<backend_name>/<board_name>/post', methods=['POST'])
def route_post(backend_name, board_name):
    backend = backend_by_name(backend_name)
    if not backend:
        print('no backend')
        return redirect('/')
    board = board_by_name(backend, board_name)
    if not board:
        print('no board')
        return redirect('/')

    def redirect_to_board():
        return redirect(f'/{backend.name}/{board.name}')

    print(request.files)
    file = request.files.get('file', None)
    content = request.form.get('content', None)
    if not content and not file:
        print('no content')
        return redirect_to_board()

    lines = content.split('\n', 1)
    m = re.match('>>(\d+)', lines[0])
    reply_to = '0'
    if m:
        reply_to = m.group(1)
        content = lines[1]

    # image upload
    if file:
        if not board.images:
            return redirect_to_board()

        _, ext = file.filename.rsplit('.', 1)
        if ext not in ['jpg', 'png']:
            flash('supported file types are .jpg, .png')
            return redirect_to_board()
        img = Image.open(file.stream)
        ansi = image_to_ansi(img, board.char_limit)
        content = ansi + content
        

    data = { 'content': content, 'replyTo': reply_to }
    r = requests.post(f'{backend.url}/{board.name}/', data=data)
    if r.status_code != 200:
        flash(f'posting failed? ({r.status_code})')
    else:
        flash(f'posting ok ({r.status_code})')
    with cache_lock:
        key = backend.name + ':' + board.name
        if key in cache:
            del cache[key]

    return redirect_to_board()

if __name__ == '__main__':
    app.run(debug=True)