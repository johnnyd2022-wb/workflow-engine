FROM ubuntu:latest
LABEL maintainer="johnny@whistlebird.co.nz"
RUN ln -snf /usr/share/zoneinfo/Pacific/Auckland /etc/localtime && echo Pacific/Auckland > /etc/timezone
RUN  apt-get -y update
COPY wb_temp/ /
EXPOSE 80
EXPOSE 443
CMD ["python", "app.py"]
