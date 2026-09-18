FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

# ── Install XFCE desktop + xrdp + dbus + basic tools ────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    dbus dbus-x11 \
    xfce4 xfce4-terminal xfce4-goodies \
    xrdp \
    x11-xserver-utils \
    sudo curl wget nano vim git \
    firefox-esr \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Create a non-root desktop user ──────────────────────────────
ARG RDP_USER=rdpuser
ARG RDP_PASS=ChangeMe123!
RUN useradd -m -s /bin/bash ${RDP_USER} && \
    echo "${RDP_USER}:${RDP_PASS}" | chpasswd && \
    usermod -aG sudo ${RDP_USER} && \
    echo "${RDP_USER} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# ── Make XFCE the default desktop session for this user ────────
# IMPORTANT: .xsession must be EXECUTABLE or xrdp's Xsession
# wrapper will silently skip it, producing a black screen.
RUN echo "#!/bin/sh" > /home/${RDP_USER}/.xsession && \
    echo "exec startxfce4" >> /home/${RDP_USER}/.xsession && \
    chmod +x /home/${RDP_USER}/.xsession && \
    chown ${RDP_USER}:${RDP_USER} /home/${RDP_USER}/.xsession

# ── Make xrdp's startwm.sh explicitly launch XFCE as a fallback ─
# (belt-and-suspenders in case .xsession isn't picked up)
RUN sed -i 's/^test -x \/etc\/X11\/Xsession.*/test -x \/etc\/X11\/Xsession \&\& exec \/etc\/X11\/Xsession\nexec startxfce4/' /etc/xrdp/startwm.sh || true

RUN mkdir -p /var/run/dbus

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3389

ENTRYPOINT ["/entrypoint.sh"]
