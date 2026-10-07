FROM alpine:3.23.3

RUN apk add --no-cache openssh-client \
    && adduser -D -u 10001 -h /home/keepalive keepalive \
    && mkdir -p /home/keepalive/.ssh /data \
    && chown -R keepalive:keepalive /home/keepalive /data

COPY --chmod=755 entrypoint.sh /usr/local/bin/frog-keepalive

USER keepalive

ENTRYPOINT ["/usr/local/bin/frog-keepalive"]
CMD ["daemon"]
