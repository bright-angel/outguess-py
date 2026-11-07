#ifndef _COMPAT_NETINET_IN_H
#define _COMPAT_NETINET_IN_H
/* little-endian host only */
#define ntohl(x) __builtin_bswap32((unsigned int)(x))
#define htonl(x) __builtin_bswap32((unsigned int)(x))
#define ntohs(x) __builtin_bswap16((unsigned short)(x))
#define htons(x) __builtin_bswap16((unsigned short)(x))
#endif
