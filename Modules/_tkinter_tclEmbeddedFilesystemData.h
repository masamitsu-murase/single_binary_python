#ifndef Py_TKINTER_TCLEMBEDDEDFILESYSTEMDATA_H
#define Py_TKINTER_TCLEMBEDDEDFILESYSTEMDATA_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    EMBEDDED_FILE_INFO_TYPE_DIRECTORY = 0,
    EMBEDDED_FILE_INFO_TYPE_FILE = 1
} EmbeddedFileInfoType;

typedef struct EmbeddedFileInfo {
    const char *name;
    EmbeddedFileInfoType type;
    const unsigned char *file_content;
    size_t file_size;
    size_t data_offset;
} EmbeddedFileInfo;

extern const unsigned char gCompressedData[];
extern unsigned char *gUncompressedData;
extern const size_t gCompressedDataSize;
extern const size_t gUncompressedDataSize;
extern EmbeddedFileInfo gEmbeddedFileInfo[];
extern const size_t gEmbeddedFileInfoCount;

int EmbeddedFileInfoDataInitialize(void);

#ifdef __cplusplus
}
#endif

#endif /* Py_TKINTER_TCLEMBEDDEDFILESYSTEMDATA_H */
