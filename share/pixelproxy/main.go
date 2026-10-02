// Tiny HTTP/HTTPS forward proxy meant to run on the Pixel via `adb shell`.
// Hotspot clients set it as their manual Wi-Fi proxy; its outbound traffic
// rides the gnirehtet VPN back to the Mac.
package main

import (
	"bufio"
	"context"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"time"
)

// Android has no /etc/resolv.conf, so Go's pure resolver must be pointed at a server.
var dialer = &net.Dialer{
	Timeout: 30 * time.Second,
	Resolver: &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return (&net.Dialer{Timeout: 10 * time.Second}).DialContext(ctx, "udp", "8.8.8.8:53")
		},
	},
}

func pipe(dst, src net.Conn) {
	io.Copy(dst, src)
	if c, ok := dst.(*net.TCPConn); ok {
		c.CloseWrite()
	}
}

func handle(c net.Conn) {
	defer c.Close()
	br := bufio.NewReader(c)
	req, err := http.ReadRequest(br)
	if err != nil {
		return
	}
	host := req.Host
	if req.Method != http.MethodConnect && req.URL.Port() == "" {
		host = net.JoinHostPort(req.URL.Hostname(), "80")
	}
	log.Printf("%s %s %s", c.RemoteAddr(), req.Method, host)

	u, err := dialer.Dial("tcp", host)
	if err != nil {
		log.Printf("  ! %s %v", host, err)
		io.WriteString(c, "HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
		return
	}
	defer u.Close()

	if req.Method == http.MethodConnect {
		io.WriteString(c, "HTTP/1.1 200 Connection Established\r\n\r\n")
	} else {
		// One request per connection, so a kept-alive client can't switch hosts mid-pipe.
		req.Header.Del("Proxy-Connection")
		req.Close = true
		req.RequestURI = ""
		if err := req.Write(u); err != nil {
			return
		}
	}
	// Anything the client already sent past the headers (e.g. TLS ClientHello) is in br.
	go func() {
		io.Copy(u, br)
		if t, ok := u.(*net.TCPConn); ok {
			t.CloseWrite()
		}
	}()
	pipe(c, u)
}

func contextTimeout(d time.Duration) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), d)
}

func main() {
	addr := ":3128"
	if len(os.Args) > 1 {
		addr = os.Args[1]
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("listening on %s", addr)
	go serveSocks(":1080")
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		go handle(c)
	}
}
