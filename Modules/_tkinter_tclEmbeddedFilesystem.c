#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>

#include <tcl.h>

#include "_tkinter_tclEmbeddedFilesystemData.h"

#ifndef F_OK
#    define F_OK 00
#endif
#ifndef X_OK
#    define X_OK 01
#endif
#ifndef W_OK
#    define W_OK 02
#endif
#ifndef R_OK
#    define R_OK 04
#endif
#ifndef O_ACCMODE
#    define O_ACCMODE (O_RDONLY | O_WRONLY | O_RDWR)
#endif

#define EMBEDDED_FS_PREFIX "embeddedfs:/"
#define EMBEDDED_FS_PREFIX_LEN 11

typedef struct {
    const unsigned char *content;
    size_t size;
    size_t pos;
} EmbeddedChannelData;

static int
EmbeddedPathInFilesystem(
    Tcl_Obj *pathPtr,
    ClientData *clientDataPtr)
{
    int len;
    const char *path;

    (void)clientDataPtr;

    path = Tcl_GetStringFromObj(pathPtr, &len);
    if (len < EMBEDDED_FS_PREFIX_LEN ||
        strncmp(path, EMBEDDED_FS_PREFIX, EMBEDDED_FS_PREFIX_LEN) != 0) {
        return -1;
    }
    return TCL_OK;
}

static const char *
EmbeddedPathWithoutPrefix(Tcl_Obj *pathPtr)
{
    int len;
    const char *path;

    path = Tcl_GetStringFromObj(pathPtr, &len);
    if (len < EMBEDDED_FS_PREFIX_LEN) {
        return NULL;
    }
    if (strncmp(path, EMBEDDED_FS_PREFIX, EMBEDDED_FS_PREFIX_LEN) != 0) {
        return NULL;
    }
    return path + EMBEDDED_FS_PREFIX_LEN;
}

static EmbeddedFileInfo *
FindFileInfo(Tcl_Obj *pathPtr)
{
    const char *relative;
    size_t left;
    size_t right;

    relative = EmbeddedPathWithoutPrefix(pathPtr);
    if (relative == NULL) {
        return NULL;
    }

    if (*relative == '\0') {
        return NULL;
    }

    left = 0;
    right = gEmbeddedFileInfoCount;

    while (left < right) {
        size_t mid = left + (right - left) / 2;
        int cmp = strcmp(gEmbeddedFileInfo[mid].name, relative);

        if (cmp == 0) {
            return &gEmbeddedFileInfo[mid];
        }
        if (cmp < 0) {
            left = mid + 1;
        }
        else {
            right = mid;
        }
    }

    return NULL;
}

static int
EmbeddedInput(
    ClientData instanceData,
    char *buf,
    int toRead,
    int *errorCodePtr)
{
    EmbeddedChannelData *channelData;
    size_t remain;
    size_t readSize;

    (void)errorCodePtr;

    channelData = (EmbeddedChannelData *)instanceData;
    if (channelData->pos >= channelData->size) {
        return 0;
    }

    remain = channelData->size - channelData->pos;
    readSize = (size_t)toRead;
    if (readSize > remain) {
        readSize = remain;
    }

    memcpy(buf, channelData->content + channelData->pos, readSize);
    channelData->pos += readSize;
    return (int)readSize;
}

static int
EmbeddedOutput(
    ClientData instanceData,
    const char *buf,
    int toWrite,
    int *errorCodePtr)
{
    (void)instanceData;
    (void)buf;
    (void)toWrite;

    if (errorCodePtr != NULL) {
        *errorCodePtr = EACCES;
    }
    return -1;
}

static Tcl_WideInt
EmbeddedWideSeek(
    ClientData instanceData,
    Tcl_WideInt offset,
    int mode,
    int *errorCodePtr)
{
    EmbeddedChannelData *channelData;
    Tcl_WideInt newPos;

    channelData = (EmbeddedChannelData *)instanceData;

    if (mode == SEEK_SET) {
        newPos = offset;
    }
    else if (mode == SEEK_CUR) {
        newPos = (Tcl_WideInt)channelData->pos + offset;
    }
    else if (mode == SEEK_END) {
        newPos = (Tcl_WideInt)channelData->size + offset;
    }
    else {
        if (errorCodePtr != NULL) {
            *errorCodePtr = EINVAL;
        }
        return (Tcl_WideInt)-1;
    }

    if (newPos < 0 || (size_t)newPos > channelData->size) {
        if (errorCodePtr != NULL) {
            *errorCodePtr = EINVAL;
        }
        return (Tcl_WideInt)-1;
    }

    channelData->pos = (size_t)newPos;
    return newPos;
}

static int
EmbeddedSeek(
    ClientData instanceData,
    long offset,
    int mode,
    int *errorCodePtr)
{
    return (int)EmbeddedWideSeek(instanceData, (Tcl_WideInt)offset, mode, errorCodePtr);
}

static int
EmbeddedClose(
    ClientData instanceData,
    Tcl_Interp *interp)
{
    (void)interp;
    ckfree((char *)instanceData);
    return TCL_OK;
}

static int
EmbeddedBlockMode(
    ClientData instanceData,
    int mode)
{
    (void)instanceData;
    (void)mode;
    return TCL_OK;
}

static void
EmbeddedWatch(
    ClientData instanceData,
    int mask)
{
    (void)instanceData;
    (void)mask;
}

static int
EmbeddedGetHandle(
    ClientData instanceData,
    int direction,
    ClientData *handlePtr)
{
    (void)instanceData;
    (void)direction;
    (void)handlePtr;
    return TCL_ERROR;
}

static Tcl_ChannelType EmbeddedChannelType = {
    "embeddedfs",
    TCL_CHANNEL_VERSION_5,
    EmbeddedClose,
    EmbeddedInput,
    EmbeddedOutput,
    EmbeddedSeek,
    NULL,
    NULL,
    EmbeddedWatch,
    EmbeddedGetHandle,
    NULL,
    EmbeddedBlockMode,
    NULL,
    NULL,
    EmbeddedWideSeek,
    NULL,
    NULL
};

static Tcl_Channel
EmbeddedOpenFileChannel(
    Tcl_Interp *interp,
    Tcl_Obj *pathPtr,
    int mode,
    int permissions)
{
    EmbeddedFileInfo *info;
    EmbeddedChannelData *channelData;
    Tcl_Channel channel;

    (void)permissions;

    info = FindFileInfo(pathPtr);
    if (info == NULL || info->type != EMBEDDED_FILE_INFO_TYPE_FILE) {
        if (interp != NULL) {
            Tcl_SetErrno(ENOENT);
            Tcl_SetObjResult(interp, Tcl_NewStringObj("no such embedded file", -1));
        }
        return NULL;
    }

    if ((mode & O_ACCMODE) != O_RDONLY) {
        if (interp != NULL) {
            Tcl_SetErrno(EACCES);
            Tcl_SetObjResult(interp, Tcl_NewStringObj("embeddedfs is read-only", -1));
        }
        return NULL;
    }

    channelData = (EmbeddedChannelData *)ckalloc(sizeof(EmbeddedChannelData));
    channelData->content = info->file_content;
    channelData->size = info->file_size;
    channelData->pos = 0;

    channel = Tcl_CreateChannel(&EmbeddedChannelType,
                                Tcl_GetString(pathPtr),
                                (ClientData)channelData,
                                TCL_READABLE);
    if (channel == NULL) {
        ckfree((char *)channelData);
        return NULL;
    }

    Tcl_SetChannelOption(interp, channel, "-translation", "binary");
    Tcl_SetChannelOption(interp, channel, "-encoding", "binary");
    return channel;
}

static int
EmbeddedAccess(
    Tcl_Obj *pathPtr,
    int mode)
{
    EmbeddedFileInfo *info;

    info = FindFileInfo(pathPtr);
    if (info == NULL) {
        Tcl_SetErrno(ENOENT);
        return -1;
    }

    if (mode == F_OK) {
        return 0;
    }

    if ((mode & W_OK) != 0) {
        Tcl_SetErrno(EACCES);
        return -1;
    }

    return 0;
}

static int
EmbeddedStat(
    Tcl_Obj *pathPtr,
    Tcl_StatBuf *buf)
{
    EmbeddedFileInfo *info;

    info = FindFileInfo(pathPtr);
    if (info == NULL) {
        Tcl_SetErrno(ENOENT);
        return -1;
    }

    memset(buf, 0, sizeof(*buf));
    if (info->type == EMBEDDED_FILE_INFO_TYPE_DIRECTORY) {
        buf->st_mode = S_IFDIR | 0555;
        buf->st_nlink = 2;
    }
    else {
        buf->st_mode = S_IFREG | 0444;
        buf->st_nlink = 1;
        buf->st_size = (long)info->file_size;
    }
    return 0;
}

static int
EmbeddedLstat(
    Tcl_Obj *pathPtr,
    Tcl_StatBuf *buf)
{
    return EmbeddedStat(pathPtr, buf);
}

static int
EmbeddedMatchInDirectory(
    Tcl_Interp *interp,
    Tcl_Obj *result,
    Tcl_Obj *pathPtr,
    const char *pattern,
    Tcl_GlobTypeData *types)
{
    const char *relative;
    size_t i;
    size_t parentLen;

    (void)interp;

    relative = EmbeddedPathWithoutPrefix(pathPtr);
    if (relative == NULL) {
        return TCL_OK;
    }

    parentLen = strlen(relative);

    for (i = 0; i < gEmbeddedFileInfoCount; i++) {
        const char *name;
        const char *rest;

        name = gEmbeddedFileInfo[i].name;

        if (parentLen == 0) {
            rest = name;
        }
        else {
            if (strncmp(name, relative, parentLen) != 0 || name[parentLen] != '/') {
                continue;
            }
            rest = name + parentLen + 1;
        }

        if (*rest == '\0' || strchr(rest, '/') != NULL) {
            continue;
        }

        if (types != NULL && (types->type & TCL_GLOB_TYPE_DIR) != 0 &&
            gEmbeddedFileInfo[i].type != EMBEDDED_FILE_INFO_TYPE_DIRECTORY) {
            continue;
        }
        if (types != NULL && (types->type & TCL_GLOB_TYPE_FILE) != 0 &&
            gEmbeddedFileInfo[i].type != EMBEDDED_FILE_INFO_TYPE_FILE) {
            continue;
        }

        if (pattern == NULL || Tcl_StringMatch(rest, pattern)) {
            Tcl_Obj *childPath;

            if (parentLen == 0) {
                childPath = Tcl_NewStringObj(EMBEDDED_FS_PREFIX, EMBEDDED_FS_PREFIX_LEN);
            }
            else {
                childPath = Tcl_NewStringObj(Tcl_GetString(pathPtr), -1);
                Tcl_AppendToObj(childPath, "/", 1);
            }
            Tcl_AppendToObj(childPath, rest, -1);
            Tcl_ListObjAppendElement(NULL, result, childPath);
        }
    }

    return TCL_OK;
}

static Tcl_Obj *
EmbeddedListVolumes(void)
{
    Tcl_Obj *retVal;

    retVal = Tcl_NewStringObj(EMBEDDED_FS_PREFIX, EMBEDDED_FS_PREFIX_LEN);
    Tcl_IncrRefCount(retVal);
    return retVal;
}

static Tcl_Obj *
EmbeddedFilesystemPathType(Tcl_Obj *pathPtr)
{
    (void)pathPtr;
    return Tcl_NewStringObj("embeddedfs", -1);
}

static Tcl_Obj *
EmbeddedFilesystemSeparator(Tcl_Obj *pathPtr)
{
    (void)pathPtr;
    return Tcl_NewStringObj("/", 1);
}

static const Tcl_Filesystem embeddedFilesystem = {
    "embeddedfs",
    sizeof(Tcl_Filesystem),
    TCL_FILESYSTEM_VERSION_1,
    EmbeddedPathInFilesystem,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    EmbeddedFilesystemPathType,
    EmbeddedFilesystemSeparator,
    EmbeddedStat,
    EmbeddedAccess,
    EmbeddedOpenFileChannel,
    EmbeddedMatchInDirectory,
    NULL,
    NULL,
    EmbeddedListVolumes,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    EmbeddedLstat,
    NULL,
    NULL,
    NULL
};

int
TclEmbeddedFilesystemRegister(void)
{
    static int registered = 0;

    if (registered) {
        return TCL_OK;
    }

    if (EmbeddedFileInfoDataInitialize() != 0) {
        return TCL_ERROR;
    }

    if (Tcl_FSRegister(NULL, &embeddedFilesystem) != TCL_OK) {
        return TCL_ERROR;
    }

    registered = 1;
    return TCL_OK;
}
