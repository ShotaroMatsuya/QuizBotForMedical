FROM python:3.11.4-buster

ENV PYTHONUNBUFFERD 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONPATH /code

RUN apt-get update && apt-get -y install --no-install-recommends awscli
ENV TZ=Asia/Tokyo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN mkdir /code/
WORKDIR /code
COPY .devcontainer/requirements.txt /code

RUN pip install --upgrade pip
RUN pip install --upgrade setuptools
RUN pip install -r requirements.txt