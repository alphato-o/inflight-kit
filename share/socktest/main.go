// On-device check: SOCKS5 UDP ASSOCIATE, then a DNS query for example.com to 8.8.8.8.
package main

import (
	"fmt"
	"io"
	"net"
	"os"
	"time"
)

func main() {
	c, err := net.Dial("tcp", os.Args[1])
	if err != nil {
		panic(err)
	}
	c.Write([]byte{5, 1, 0})
	io.ReadFull(c, make([]byte, 2))
	c.Write([]byte{5, 3, 0, 1, 0, 0, 0, 0, 0, 0})
	r := make([]byte, 10)
	io.ReadFull(c, r)
	relay := &net.UDPAddr{IP: net.IP(r[4:8]), Port: int(r[8])<<8 | int(r[9])}
	fmt.Println("relay at", relay)
	u, _ := net.DialUDP("udp", nil, relay)
	q := []byte{0x12, 0x34, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 7, 'e', 'x', 'a', 'm', 'p', 'l', 'e', 3, 'c', 'o', 'm', 0, 0, 1, 0, 1}
	u.Write(append([]byte{0, 0, 0, 1, 8, 8, 8, 8, 0, 53}, q...))
	u.SetReadDeadline(time.Now().Add(15 * time.Second))
	b := make([]byte, 1500)
	n, err := u.Read(b)
	if err != nil {
		fmt.Println("UDP FAIL:", err)
		return
	}
	a := b[n-4 : n]
	fmt.Printf("UDP OK: %d bytes, example.com -> %d.%d.%d.%d\n", n, a[0], a[1], a[2], a[3])
}
