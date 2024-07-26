FROM python:3.12-slim-bookworm

RUN apt-get -y update \
    && apt-get -y install --no-install-recommends curl tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ENV PYTHONDONTWRITEBYTECODE="1" PYTHONIOENCODING="UTF-8" PYTHONUNBUFFERED="1"

# dir and user setup
ENV USER="faucet"
RUN adduser --disabled-password $USER
USER $USER
ENV APP_DIR="/home/$USER/faucet"
WORKDIR $APP_DIR

# project setup
RUN python3 -m pip install --no-cache-dir poetry \
    && echo "export PATH=$PATH:$HOME/.local/bin" >> $HOME/.bashrc
COPY --chown=$USER:$USER poetry.lock pyproject.toml ./

# install project dependencies
RUN $HOME/.local/bin/poetry install --without=dev

# copy project code
COPY --chown=$USER:$USER faucet_rgb ./faucet_rgb
COPY --chown=$USER:$USER migrations ./migrations
COPY --chown=$USER:$USER issue_asset.py wallet_helper.py LICENSE README.md ./

EXPOSE 8080/tcp
HEALTHCHECK CMD curl localhost:8080 || exit 1

CMD ["tini", "--", "/home/faucet/.local/bin/poetry", "run", "waitress-serve", "--host=0.0.0.0", "--call", "faucet_rgb:create_app"]
