package main

// Minimal SOCKS5 server (RFC 1928): no auth, CONNECT and UDP ASSOCIATE.
// UDP is what lets voice/video calls (e.g. WeChat) work through the Pixel.

import (
	"bufio"
	"encoding/binary"
	"errors"
	"io"
	"log"
	"net"
	"strconv"
	"sync/atomic"
	"time"
)

const (
	cmdConnect      = 1
	cmdUDPAssociate = 3
)

func serveSocks(addr string) {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("socks5 listening on %s", addr)
	for {
		c, err := ln.Accept()
		if err != nil {
			continue
		}
		go handleSocks(c)
	}
}

// readAddr parses ATYP, DST.ADDR, DST.PORT and returns "host:port".
func readAddr(r io.Reader) (string, error) {
	var atyp [1]byte
	if _, err := io.ReadFull(r, atyp[:]); err != nil {
		return "", err
	}
	var host string
	switch atyp[0] {
	case 1:
		b := make([]byte, 4)
		if _, err := io.ReadFull(r, b); err != nil {
			return "", err
		}
		host = net.IP(b).String()
	case 4:
		b := make([]byte, 16)
		if _, err := io.ReadFull(r, b); err != nil {
			return "", err
		}
		host = net.IP(b).String()
	case 3:
		var n [1]byte
		if _, err := io.ReadFull(r, n[:]); err != nil {
			return "", err
		}
		b := make([]byte, n[0])
		if _, err := io.ReadFull(r, b); err != nil {
			return "", err
		}
		host = string(b)
	default:
		return "", errors.New("bad address type")
	}
	var p [2]byte
	if _, err := io.ReadFull(r, p[:]); err != nil {
		return "", err
	}
	return net.JoinHostPort(host, strconv.Itoa(int(binary.BigEndian.Uint16(p[:])))), nil
}

// encodeAddr builds ATYP + ADDR + PORT for an IP address.
func encodeAddr(a *net.UDPAddr) []byte {
	var b []byte
	if ip4 := a.IP.To4(); ip4 != nil {
		b = append([]byte{1}, ip4...)
	} else {
		b = append([]byte{4}, a.IP.To16()...)
	}
	return binary.BigEndian.AppendUint16(b, uint16(a.Port))
}

func reply(c net.Conn, rep byte, bind *net.UDPAddr) {
	if bind == nil {
		bind = &net.UDPAddr{IP: net.IPv4zero}
	}
	c.Write(append([]byte{5, rep, 0}, encodeAddr(bind)...))
}

func handleSocks(c net.Conn) {
	defer c.Close()
	br := bufio.NewReader(c)

	// Greeting: VER NMETHODS METHODS. We only offer "no auth".
	var hdr [2]byte
	if _, err := io.ReadFull(br, hdr[:]); err != nil || hdr[0] != 5 {
		return
	}
	if _, err := io.ReadFull(br, make([]byte, hdr[1])); err != nil {
		return
	}
	c.Write([]byte{5, 0})

	// Request: VER CMD RSV then address.
	var req [3]byte
	if _, err := io.ReadFull(br, req[:]); err != nil {
		return
	}
	dst, err := readAddr(br)
	if err != nil {
		return
	}

	switch req[1] {
	case cmdConnect:
		log.Printf("%s SOCKS %s", c.RemoteAddr(), dst)
		u, err := dialer.Dial("tcp", dst)
		if err != nil {
			log.Printf("  ! %s %v", dst, err)
			reply(c, 5, nil)
			return
		}
		defer u.Close()
		reply(c, 0, nil)
		go func() {
			io.Copy(u, br)
			if t, ok := u.(*net.TCPConn); ok {
				t.CloseWrite()
			}
		}()
		pipe(c, u)
	case cmdUDPAssociate:
		udpAssociate(c)
	default:
		reply(c, 7, nil)
	}
}

// udpAssociate relays datagrams for one client until its TCP control connection closes.
func udpAssociate(c net.Conn) {
	localIP := c.LocalAddr().(*net.TCPAddr).IP
	clientIP := c.RemoteAddr().(*net.TCPAddr).IP

	relay, err := net.ListenUDP("udp", &net.UDPAddr{IP: localIP})
	if err != nil {
		reply(c, 1, nil)
		return
	}
	defer relay.Close()
	out, err := net.ListenUDP("udp", nil)
	if err != nil {
		reply(c, 1, nil)
		return
	}
	defer out.Close()
	reply(c, 0, relay.LocalAddr().(*net.UDPAddr))
	log.Printf("%s UDP associate via %s", c.RemoteAddr(), relay.LocalAddr())

	var client atomic.Pointer[net.UDPAddr]
	resolved := map[string]*net.UDPAddr{}

	// Client -> internet.
	go func() {
		buf := make([]byte, 65535)
		for {
			n, from, err := relay.ReadFromUDP(buf)
			if err != nil {
				return
			}
			if !from.IP.Equal(clientIP) || n < 4 || buf[2] != 0 { // fragments unsupported
				continue
			}
			client.Store(from)
			r := &sliceReader{b: buf[3:n]}
			dst, err := readAddr(r)
			if err != nil {
				continue
			}
			ua, ok := resolved[dst]
			if !ok {
				if ua, err = resolveUDP(dst); err != nil {
					continue
				}
				resolved[dst] = ua
			}
			out.WriteToUDP(r.b, ua)
		}
	}()

	// Internet -> client.
	go func() {
		buf := make([]byte, 65535)
		for {
			n, from, err := out.ReadFromUDP(buf)
			if err != nil {
				return
			}
			cl := client.Load()
			if cl == nil {
				continue
			}
			pkt := append(append([]byte{0, 0, 0}, encodeAddr(from)...), buf[:n]...)
			relay.WriteToUDP(pkt, cl)
		}
	}()

	// The association lives as long as the TCP connection.
	io.Copy(io.Discard, c)
}

func resolveUDP(hostport string) (*net.UDPAddr, error) {
	host, port, err := net.SplitHostPort(hostport)
	if err != nil {
		return nil, err
	}
	if ip := net.ParseIP(host); ip != nil {
		p, _ := strconv.Atoi(port)
		return &net.UDPAddr{IP: ip, Port: p}, nil
	}
	ctx, cancel := contextTimeout(10 * time.Second)
	defer cancel()
	ips, err := dialer.Resolver.LookupIP(ctx, "ip4", host)
	if err != nil || len(ips) == 0 {
		return nil, errors.New("resolve failed: " + host)
	}
	p, _ := strconv.Atoi(port)
	return &net.UDPAddr{IP: ips[0], Port: p}, nil
}

type sliceReader struct{ b []byte }

func (s *sliceReader) Read(p []byte) (int, error) {
	if len(s.b) == 0 {
		return 0, io.EOF
	}
	n := copy(p, s.b)
	s.b = s.b[n:]
	return n, nil
}
