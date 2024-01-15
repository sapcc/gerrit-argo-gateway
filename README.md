# gerrit-argo-gateway

A small service connecting to the gerrit event stream via ssh to (Argo Workflows Events API)[https://github.com/argoproj/argo-workflows/blob/master/docs/events.md].

Configuration happens via environment variables
The `ARGO_*` variables are the same ones as show under the user info tab.

* `ARGO_SERVER` the name of the of the server (optionally a port)
* `ARGO_TOKEN` the secret token to use to authenticate
* `ARGO_NAMESPACE` in which namspace the events should be posted
* `GERRIT_SERVER` is of the form `<username>@<host>:<port>`. It will use the standard ssh keys, unless `SSH_PRIVATE_KEY` is set.
* `SSH_PRIVATE_KEY_PATH` is the optional path to an openssh private key in text form.

For testing it with `rundocker.sh`, place the environment variables except `SSH_PRIVATE_KEY_PATH` into a `.env`-file.
Notice, that the values should not be quoted, even if they contain white-spaces.
