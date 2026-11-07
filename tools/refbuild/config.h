/* Minimal config.h for native Windows build of outguess 0.4 (zig/clang, MinGW) */
#define HAVE_STDC_HEADERS 1
#define HAVE_STDDEF_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_STRINGS_H 1
#define HAVE_FCNTL_H 1
#define HAVE_UNISTD_H 1
#define HAVE_SYS_STAT_H 1
#define HAVE_MALLOC_H 1
#define HAVE_MEMMOVE 1
#define HAVE_MEMSET 1
#define HAVE_SQRT 1
#define HAVE_STRCHR 1
#define HAVE_STRRCHR 1
#define HAVE_STRERROR 1
#define HAVE_SNPRINTF 1
#define HAVE_STRCASECMP 1
#define STDC_HEADERS 1

/* MinGW does not provide the BSD integer typedefs used by outguess */
typedef unsigned char u_char;
typedef unsigned char u_int8_t;
typedef unsigned short u_int16_t;
typedef unsigned int u_int32_t;
typedef unsigned long u_int64_t;
typedef unsigned int u_int;
typedef unsigned short u_short;
typedef unsigned long u_long;

/* Windows: force binary mode for the raw read() used by mmap_file() */
#if defined(_WIN32) && !defined(_OUTGUESS_COMPAT_OPEN)
#define _OUTGUESS_COMPAT_OPEN
#include <io.h>
#include <fcntl.h>
static __inline int outguess_compat_open(const char *p, int f, int m)
{ return _open(p, f | _O_BINARY, m); }
#define open(p,f,m) outguess_compat_open(p,f,m)
#endif
