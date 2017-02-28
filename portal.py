#!/usr/bin/env python3

import os
import datetime
import argparse
# import logging

from flask import (
    Flask,
    abort,
    flash,
    json,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from flask_sqlalchemy import SQLAlchemy, _QueryProperty

import model as m
# Default ordering for admin types
m.Semesters.order_by = m.Semesters.title
m.Professors.order_by = m.Professors.last_first
m.Courses.order_by = m.Courses.number
m.Sections.order_by = m.Sections.number
m.ProblemTypes.order_by = m.ProblemTypes.description

# Create App
app = Flask(__name__)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Attach Database
db = SQLAlchemy(app)
db.Model = m.Base
# Ugly code to make Base.query work
m.Base.query_class = db.Query
m.Base.query = _QueryProperty(db)


def create_app(args):
    r"""
    Sets up app for use
    Adds logging, database configuration, and the secret key
    """
    global app, db
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    # setup Logging
    # log = logging.getLogger('FlaskApp')
    # log.setLevel(logging.ERROR)
    # app.logger.addHandler(log)

    # setup Database
    app.config['SQLALCHEMY_DATABASE_URI'] = '{}:///{}'.format(
        args.type, args.database)
    db.create_all()

    # setup config values
    with app.app_context():
        config = {
            'SECRET_KEY': os.urandom(24),
            'PERMANENT_SESSION_LIFETIME': '30',
        }
        # get Config values from database
        for name in config:
            try:
                key = m.Config.query.filter_by(name=name).one()
                config[name] = key.value
            except NoResultFound:
                key = m.Config(name=name, value=config[name])
                db.session.add(key)
                db.session.commit()

        config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(
            minutes=int(config['PERMANENT_SESSION_LIFETIME']))
        app.config.update(config)


def date(string):
    r"""
    Convert a date formated string to a date object
    """
    return datetime.datetime.strptime(string, '%Y-%m-%d').date()


def get_int(string):
    r"""
    Convert a string to int returning none for invalid strings
    """
    ret = None
    if string is not None:
        try:
            ret = int(string)
        except ValueError:
            pass
    return ret


@app.context_processor
def context():
    return dict(m=m)


def error(e, message):
    r"""
    Basic error template for all error pages
    """
    user = get_user()
    html = render_template(
        'error.html',
        title=str(e),
        message=message,
        user=user,
    )
    return html


@app.errorhandler(403)
def four_oh_three(e):
    r"""
    403 (forbidden) error page
    """
    return error(
        e,
        "You don't have access to this page."
    ), 403


@app.errorhandler(404)
def four_oh_four(e):
    r"""
    404 (page not found) error page
    """
    return error(
        e,
        "We couldn't find the page you were looking for."
    ), 404


@app.errorhandler(500)
def five_hundred(e):
    r"""
    500 (internal server) error page
    Will have to be changed for production version
    """
    if isinstance(e, NoResultFound):
        message = 'Could not find the requested item in the database.'
    elif isinstance(e, MultipleResultsFound):
        message = 'Found too many results for the requested resource.'
    else:
        message = 'Whoops, looks like something went wrong!'
    return error(
        '500: '+str(e),
        message,
    ), 500


def get_user():
    r"""
    Gets the user data from the current session
    Returns the Tutor object of the current user
    """
    id = session.get('username')
    user = None
    if id:
        if app.config['DEBUG']:
            user = m.Tutors(email=id, is_active=True, is_superuser=True)
        else:
            try:
                user = m.Tutors.query.filter_by(email=id).one()
            except NoResultFound:
                session.clear()

        if user and not user.is_active:
            session.clear()
            user = None
    return user


@app.route('/favicon.ico')
def favicon():
    r"""
    The favorites icon for the site
    """
    return send_from_directory(
        os.path.join(app.root_path, 'static', 'images'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon',
    )


@app.route('/')
def index():
    r"""
    The home page, from which tutors can login and students can open tickets
    """
    user = get_user()
    html = render_template(
        'index.html',
        home=True,
        user=user,
    )
    return html


@app.route('/status.html')
def status():
    r"""
    A status page for the CSLC

    For students displays:
        Annoucements
        Course Availability

    For tutors, also displays:
        Open Tickets
    """
    user = get_user()
    html = render_template(
        'status.html',
        user=user,
    )
    return html


@app.route('/open_ticket/')
def open_ticket():
    r"""
    The student page for opening a ticket
    """
    user = get_user()

    today = datetime.date.today()
    courses = m.Courses.query.join(m.Sections).join(m.Semesters).\
        order_by(m.Courses.number).\
        order_by(m.Sections.number).\
        filter(m.Semesters.start_date <= today).\
        filter(m.Semesters.end_date >= today).\
        all()
    problems = m.ProblemTypes.query.order_by(m.ProblemTypes.description).all()

    html = render_template(
        'open_ticket.html',
        user=user,
        courses=courses,
        problems=problems,
    )
    return html


@app.route('/open_ticket/', methods=['POST'])
def save_open_ticket():
    r"""
    Saves changes to a ticket
    """
    user = get_user()

    get = request.form.get
    ticket = m.Tickets(
        student_email=get('student_email'),
        student_fname=get('student_fname'),
        student_lname=get('student_lname'),
        section_id=int(get('section_id')),
        assignment=get('assignment'),
        question=get('question'),
        problem_type_id=int(get('problem_type_id')),
        status=m.Status.Open,
        time_created=datetime.datetime.now(),
    )
    db.session.add(ticket)
    db.session.commit()

    html = redirect(url_for('index'))
    flash('&#10004; Ticket successfully opened')
    return html


@app.route('/tickets/')
def view_tickets():
    r"""
    View/Claim/Close tickets
    """
    user = get_user()
    if not user:
        return redirect(url_for('login'))

    tickets = m.Tickets.query.order_by(m.Tickets.time_created).\
        join(m.Sections).\
        join(m.Semesters).\
        join(m.Courses).\
        filter((m.Tickets.time_created > datetime.datetime.now()) |
            (m.Tickets.status.in_((None, m.Status.Open, m.Status.Claimed)))).\
        all()

    open = filter(lambda a: a.status in (None, m.Status.Open), tickets)
    claimed = filter(lambda a: a.status == m.Status.Claimed, tickets)
    closed = filter(lambda a: a.status == m.Status.Closed, tickets)

    html = render_template(
        'tickets.html',
        user=user,
        open=open,
        claimed=claimed,
        closed=closed,
    )
    return html


@app.route('/tickets/close/<id>')
def close_ticket(id):
    r"""
    The tutor page for claiming and closing tickets
    """
    user = get_user()
    if not user:
        return abort(403)

    html = render_template(
        'close_ticket.html',
        user=user,
    )
    return html


@app.route('/tickets/reopen/<id>')
def reopen_ticket(id):
    r"""
    Moves a ticket from closed to claimed
    """
    user = get_user()
    if not user:
        return abort(403)

    ticket = m.Tickets.query.filter_by(id=id).one()
    ticket.status = m.Status.claimed
    db.session.commit()

    return redirect(url_for('view_tickets'))


# ----#-   Administration tools
@app.route('/admin/')
def admin():
    r"""
    The admin configutration page
    Can add professors, semesters, courses, sections, tutors, and more
    """
    user = get_user()
    if not user or not user.is_superuser:
        return abort(403)

    html = render_template(
        'admin.html',
        user=user,
    )
    return html


@app.route('/admin/semesters/', defaults={'type': m.Semesters})
@app.route('/admin/professors/', defaults={'type': m.Professors})
@app.route('/admin/courses/', defaults={'type': m.Courses})
@app.route('/admin/sections/', defaults={'type': m.Sections})
@app.route('/admin/problems/', defaults={'type': m.ProblemTypes})
def list_admin(type):
    r"""
    Displays and allows editing of the available admin objects
    """
    user = get_user()
    if not user or not user.is_superuser:
        return abort(403)

    title = {
        m.Semesters: 'Semesters',
        m.Professors: 'Professors',
        m.Courses: 'Courses',
        m.Sections: 'Course Sections',
        m.ProblemTypes: 'Problem Types',
    }.get(type)

    html = render_template(
        'list_admin.html',
        user=user,
        title=title,
        type=type,
        items=type.query.order_by(type.order_by).all(),
    )
    return html


@app.route('/admin/semesters/new', defaults={'type': m.Semesters})
@app.route('/admin/professors/new', defaults={'type': m.Professors})
@app.route('/admin/courses/new', defaults={'type': m.Courses})
@app.route('/admin/sections/new', defaults={'type': m.Sections})
@app.route('/admin/problems/new', defaults={'type': m.ProblemTypes})
@app.route('/admin/semesters/<int:id>', defaults={'type': m.Semesters})
@app.route('/admin/professors/<int:id>', defaults={'type': m.Professors})
@app.route('/admin/courses/<int:id>', defaults={'type': m.Courses})
@app.route('/admin/sections/<int:id>', defaults={'type': m.Sections})
@app.route('/admin/problems/<int:id>', defaults={'type': m.ProblemTypes})
def edit_admin(type, id=None):
    r"""
    Allows editing and creation of admin objects
    """
    user = get_user()
    if not user or not user.is_superuser:
        return abort(403)

    if id is None:
        obj = None
    else:
        obj = type.query.filter_by(id=id).one()

    html = render_template(
        'edit_%s.html' % type.__tablename__,
        user=user,
        type=type,
        obj=obj,
    )
    return html


semester_form = {
    'year': get_int,
    'season': lambda a: m.Seasons(int(a)),
    'start_date': date,
    'end_date': date,
}
professor_form = {
    'fname': str,
    'lname': str,
}
course_form = {
    'number': str,
    'name': str,
    'on_display': bool,
}
section_form = {
    'number': str,
    'time': str,
    'course_id': get_int,
    'semester_id': get_int,
    'professor_id': get_int,
}
problem_form = {
    'description': str,
}


@app.route(
    '/admin/semesters/', methods=['POST'], defaults={'type': m.Semesters})
@app.route(
    '/admin/professors/', methods=['POST'], defaults={'type': m.Professors})
@app.route(
    '/admin/courses/', methods=['POST'], defaults={'type': m.Courses})
@app.route(
    '/admin/sections/', methods=['POST'], defaults={'type': m.Sections})
@app.route(
    '/admin/problems/', methods=['POST'], defaults={'type': m.ProblemTypes})
def edited_admin(type):
    r"""
    Handles changes to administrative objects
    """
    user = get_user()
    if not user or not user.is_superuser:
        return abort(403)

    if request.form.get('action') == 'delete':
        obj = type.query.filter_by(id=request.form.get('id')).one()
        db.session.delete(obj)
    else:
        form = {
            m.Semesters: semester_form,
            m.Professors: professor_form,
            m.Courses: course_form,
            m.Sections: section_form,
            m.ProblemTypes: problem_form,
        }.get(type).copy()
        for key, value in form.items():
            form[key] = value(request.form.get(key))

        id = request.form.get('id')
        if id:
            obj = type.query.filter_by(id=id).one()
            for key, value in form.items():
                if getattr(obj, key) != value:
                    setattr(obj, key, value)
        else:
            obj = type(**form)
            db.session.add(obj)
    db.session.commit()
    return redirect(url_for('list_admin', type=type))


@app.route('/admin/tutors/')
def list_tutors():
    r"""
    Displays and allows editing of the tutors
    """
    user = get_user()
    if not user or not user.is_superuser:
        return abort(403)

    html = render_template(
        'list_tutors.html',
        user=user,
        items=m.Tutors.query.order_by(m.Tutors.last_first).all(),
    )
    return html


@app.route('/admin/tutors/new')
@app.route('/admin/tutors/<email>')
def edit_tutors(email=None):
    r"""
    Allows editing and creation of tutor objects
    """
    user = get_user()
    if not user or not (user.is_superuser or user.email == email):
        return abort(403)

    if email is None:
        tutor = None
    else:
        tutor = m.Tutors.query.filter_by(email=email).one()

    html = render_template(
        'edit_tutors.html',
        user=user,
        type=m.Tutors,
        obj=tutor,
        courses=m.Courses.query.order_by(m.Courses.number).all(),
    )
    return html


@app.route('/admin/tutors/', methods=['POST'])
def edited_tutors():
    r"""
    Handles changes to tutor objects
    """
    user = get_user()
    email = request.form.get('email')
    if not user or not (user.is_superuser or user.email == email):
        return abort(403)

    if request.form.get('action') == 'delete':
        obj = type.query.filter_by(email=email).one()
        db.session.delete(obj)
    else:
        form = {
            'fname': str,
            'lname': str,
        }
        if user.is_superuser:
            form.update({
                'is_active': bool,
                'is_superuser': bool,
            })
        for key, value in form.items():
            form[key] = value(request.form.get(key))

        if not request.form.get('new'):
            obj = m.Tutors.query.filter_by(email=email).one()
            for key, value in form.items():
                if getattr(obj, key) != value:
                    setattr(obj, key, value)
        else:
            obj = m.Tutors(email=email, **form)
            db.session.add(obj)

        for course in m.Courses.query.all():
            if request.form.get(course.number):
                if course not in obj.courses:
                    obj.courses.append(course)
            else:
                if course in obj.courses:
                    obj.courses.remove(course)

    db.session.commit()
    if user.is_superuser:
        html = redirect(url_for('list_tutors'))
    else:
        html = redirect(url_for('index'))
    return html


# ----#-   Login/Logout
@app.route('/login/')
def login():
    r"""
    Redirects the user to the UNO Single Sign On page
    """
    session.clear()
    if app.config['DEBUG']:
        session['username'] = 'test@unomaha.edu'
        html = redirect(url_for('index'))
    else:
        html = redirect('https://auth.unomaha.edu/idp/Authn/UserPassword')
    return html


@app.route('/logout/')
def logout():
    r"""
    Logs the user out and returns them to the homepage
    """
    session.clear()
    html = redirect(url_for('index'))
    return html


# ----#-   JSON
@app.route('/tickets.json')
def json_status():
    r"""
    Query needs checking
    """
    user = get_user()
    if not user:
        return abort(403)

    data = m.Tickets.query.filter(
        m.Tickets.status.in_((None, m.Status.Open))
    ).all()
    data = list(map(lambda a: a.dict(), data))
    return json.jsonify(d=data)


@app.route('/availability.json')
def json_availability():
    r"""
    Query needs checking
    Output needs checking
    """
    today = datetime.date.today()
    data = m.Courses.query.\
        join(m.can_tutor_table).join(m.Tutors).\
        join(m.Sections).join(m.Tickets).join(m.Semesters).\
        filter(m.Courses.on_display is True).\
        filter(m.Tickets.in_((None, m.Status.Open, m.Status.Claimed))).\
        filter(m.Semesters.start_date <= today).\
        filter(m.Semesters.end_date >= today).\
        all()
    lst = []
    for course in data:
        tickets = sum(len(section.tickets) for section in course.sections)
        tutors = len(course.tutors)
        lst.append({'course': course, 'tickets': tickets, 'tutors': tutors})
    return json.jsonify(d=data)


def main():
    port = 80  # default port
    parser = argparse.ArgumentParser(
        description='Tutoring Portal Server',
        epilog='The server runs locally on port %d if PORT is not specified.'
        % port)
    parser.add_argument(
        '-p, --port', dest='port', type=int,
        help='The port where the server will run')
    parser.add_argument(
        '-d, --database', dest='database', default=':memory:',
        help='The database to be accessed')
    parser.add_argument(
        '-t, --type', dest='type', default='sqlite',
        help='The type of database engine to be used')
    parser.add_argument(
        '--debug', dest='debug', action='store_true',
        help='run the server in debug mode')
    parser.add_argument(
        '--reload', dest='reload', action='store_true',
        help='reload on source update without restarting server (also debug)')
    args = parser.parse_args()
    if args.reload:
        args.debug = True

    if args.port is None:  # Private System
        args.port = port
        host = '127.0.0.1'
    else:  # Public System
        host = '0.0.0.0'

    create_app(args)

    app.run(
        host=host,
        port=args.port,
        debug=args.debug,
        use_reloader=args.reload,
    )

if __name__ == '__main__':
    main()
