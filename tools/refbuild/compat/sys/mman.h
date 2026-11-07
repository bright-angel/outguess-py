#ifndef _COMPAT_SYS_MMAN_H
#define _COMPAT_SYS_MMAN_H
/* outguess uses mmap only when HAVE_MMAP is defined; this build uses read() */
#ifndef MAP_FAILED
#define MAP_FAILED ((void *)-1)
#endif
#endif
