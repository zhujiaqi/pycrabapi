# pycrabapi

Drop in Python API for projects not so big

### Key Features

* Run out of box HTTP API...can be restful too if you like
* Human-friendly API syntax...self-doc is possible
* Comes with a concurrent logger which may rorate at midnight


###Dependencies (pip is highly recommended):

    Python 2.7
    PyMySQL
    redis
    Jinja2
    simpleflake
    mock
    uWSGI

###Run with uWSGI:

command line (run on 18888 http for example
):

  uwsgi --wsgi-file japi.py --http :18888

Sample uWSGI config file: api.template.yaml

###Build your own api from here:

Take a look at controllers/internal.py

    # sample router
    def index(args, me, meta):
        routes = {
            'GET': [
                ('^sleep$', sleep),
                ('^noop$', noop),
                ('^echo\/(?P<foo>.+)$', echo, {'myvar': 'bar'}),
                ('^sample\/(?P<account_id>.+)$', get_account),
            ],
            'POST': [
                ('^multiapi$', multiapi),
            ]
        }
        return route(routes, args, me, meta)

    #sample api
    @param('duration', False, lambda x: x in ['short', 'long'] and x or error(10010, {'duration': x}))
    def sleep(args, me, meta):
        start = time.time()
        duration = args.get('duration') or 'short'
        if duration == 'short':
            time.sleep(1)
        else:
            time.sleep(10)
        end = time.time()
        return {
            'time_elapsed': end - start,
        }
