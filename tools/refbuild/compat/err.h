#ifndef _COMPAT_ERR_H
#define _COMPAT_ERR_H
void err(int eval, const char *fmt, ...);
void warn(const char *fmt, ...);
void errx(int eval, const char *fmt, ...);
void warnx(const char *fmt, ...);
#endif
