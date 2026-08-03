#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <arpa/inet.h>
#include <netinet/in.h>

typedef struct {
  pthread_mutex_t mutex;
  pthread_cond_t condition;
  int64_t generation;
} HarnessMailbox;

void *harness_mailbox_open(void) {
  HarnessMailbox *mailbox = calloc(1, sizeof(*mailbox));
  if (!mailbox) return NULL;
  if (pthread_mutex_init(&mailbox->mutex, NULL) != 0) {
    free(mailbox);
    return NULL;
  }
  if (pthread_cond_init(&mailbox->condition, NULL) != 0) {
    pthread_mutex_destroy(&mailbox->mutex);
    free(mailbox);
    return NULL;
  }
  mailbox->generation = 1;
  return mailbox;
}

int64_t harness_mailbox_generation(void *opaque) {
  HarnessMailbox *mailbox = opaque;
  pthread_mutex_lock(&mailbox->mutex);
  int64_t generation = mailbox->generation;
  pthread_mutex_unlock(&mailbox->mutex);
  return generation;
}

int64_t harness_mailbox_notify(void *opaque) {
  HarnessMailbox *mailbox = opaque;
  if (!mailbox) return -1;
  pthread_mutex_lock(&mailbox->mutex);
  mailbox->generation++;
  pthread_cond_broadcast(&mailbox->condition);
  pthread_mutex_unlock(&mailbox->mutex);
  return 0;
}

int64_t harness_mailbox_wait(void *opaque, int64_t observed, int64_t timeout_ms) {
  HarnessMailbox *mailbox = opaque;
  if (!mailbox || timeout_ms <= 0) return 0;
  struct timespec deadline;
  if (clock_gettime(CLOCK_REALTIME, &deadline) != 0) return -1;
  deadline.tv_sec += timeout_ms / 1000;
  deadline.tv_nsec += (timeout_ms % 1000) * 1000000;
  if (deadline.tv_nsec >= 1000000000) {
    deadline.tv_sec++;
    deadline.tv_nsec -= 1000000000;
  }
  pthread_mutex_lock(&mailbox->mutex);
  int rc = 0;
  while (mailbox->generation == observed && rc == 0)
    rc = pthread_cond_timedwait(&mailbox->condition, &mailbox->mutex, &deadline);
  int changed = mailbox->generation != observed;
  pthread_mutex_unlock(&mailbox->mutex);
  return changed ? 1 : (rc == ETIMEDOUT ? 0 : -1);
}

int64_t harness_mailbox_lock(void *opaque) {
  return pthread_mutex_lock(&((HarnessMailbox *)opaque)->mutex);
}

int64_t harness_mailbox_unlock(void *opaque) {
  return pthread_mutex_unlock(&((HarnessMailbox *)opaque)->mutex);
}

int64_t harness_mailbox_close(void *opaque) {
  HarnessMailbox *mailbox = opaque;
  if (!mailbox) return 0;
  pthread_cond_destroy(&mailbox->condition);
  pthread_mutex_destroy(&mailbox->mutex);
  free(mailbox);
  return 0;
}

typedef struct {
  int read_fd;
  int write_fd;
  struct sigaction old_int;
  struct sigaction old_term;
  int installed;
} HarnessShutdown;

static volatile sig_atomic_t shutdown_write_fd = -1;

static void harness_shutdown_handler(int signal_number) {
  (void)signal_number;
  int fd = shutdown_write_fd;
  if (fd >= 0) {
    unsigned char byte = 1;
    (void)write(fd, &byte, 1);
  }
}

void *harness_shutdown_open(void) {
  HarnessShutdown *shutdown = calloc(1, sizeof(*shutdown));
  int fds[2];
  if (!shutdown || pipe(fds) != 0) {
    free(shutdown);
    return NULL;
  }
  shutdown->read_fd = fds[0];
  shutdown->write_fd = fds[1];
  fcntl(fds[0], F_SETFL, fcntl(fds[0], F_GETFL) | O_NONBLOCK);
  fcntl(fds[1], F_SETFL, fcntl(fds[1], F_GETFL) | O_NONBLOCK);
  return shutdown;
}

int64_t harness_shutdown_install(void *opaque) {
  HarnessShutdown *shutdown = opaque;
  if (!shutdown) return -1;
  struct sigaction action = {0};
  sigemptyset(&action.sa_mask);
  action.sa_handler = harness_shutdown_handler;
  action.sa_flags = 0;
  shutdown_write_fd = shutdown->write_fd;
  if (sigaction(SIGINT, &action, &shutdown->old_int) != 0) {
    shutdown_write_fd = -1;
    return -1;
  }
  if (sigaction(SIGTERM, &action, &shutdown->old_term) != 0) {
    sigaction(SIGINT, &shutdown->old_int, NULL);
    shutdown_write_fd = -1;
    return -1;
  }
  shutdown->installed = 1;
  return 0;
}

int64_t harness_shutdown_request(void *opaque) {
  HarnessShutdown *shutdown = opaque;
  if (!shutdown) return -1;
  unsigned char byte = 1;
  ssize_t written = write(shutdown->write_fd, &byte, 1);
  return written == 1 || errno == EAGAIN ? 0 : -1;
}

int64_t harness_shutdown_requested(void *opaque) {
  HarnessShutdown *shutdown = opaque;
  if (!shutdown) return 1;
  struct pollfd descriptor = {shutdown->read_fd, POLLIN, 0};
  return poll(&descriptor, 1, 0) > 0 ? 1 : 0;
}

/* 1 = listener, 0 = timeout, 2 = shutdown, -1 = error. */
int64_t harness_shutdown_wait_listener(void *opaque, int listener_fd, int timeout_ms) {
  HarnessShutdown *shutdown = opaque;
  struct pollfd descriptors[2] = {
    {listener_fd, POLLIN, 0}, {shutdown->read_fd, POLLIN, 0}
  };
  int rc;
  do rc = poll(descriptors, 2, timeout_ms); while (rc < 0 && errno == EINTR);
  if (rc < 0) return -1;
  if (rc == 0) return 0;
  if (descriptors[1].revents) return 2;
  return descriptors[0].revents ? 1 : -1;
}

int64_t harness_shutdown_close(void *opaque) {
  HarnessShutdown *shutdown = opaque;
  if (!shutdown) return 0;
  if (shutdown->installed) {
    sigaction(SIGINT, &shutdown->old_int, NULL);
    sigaction(SIGTERM, &shutdown->old_term, NULL);
    shutdown_write_fd = -1;
  }
  close(shutdown->read_fd);
  close(shutdown->write_fd);
  free(shutdown);
  return 0;
}

int64_t harness_accept_with_timeout(int listener_fd, int timeout_ms) {
  int client_fd = accept(listener_fd, NULL, NULL);
  if (client_fd < 0) return -1;
  struct timeval timeout = {
    .tv_sec = timeout_ms / 1000,
    .tv_usec = (timeout_ms % 1000) * 1000
  };
  if (setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0 ||
      setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0) {
    close(client_fd);
    return -1;
  }
  return client_fd;
}

int64_t harness_open_partial_client(int port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in address = {0};
  if (fd < 0) return -1;
  address.sin_family = AF_INET;
  address.sin_port = htons((uint16_t)port);
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0 ||
      write(fd, "GET /", 5) != 5) {
    close(fd);
    return -1;
  }
  return fd;
}

typedef struct HarnessAllocationNode {
  void *pointer;
  struct HarnessAllocationNode *next;
} HarnessAllocationNode;

typedef struct {
  HarnessAllocationNode *head;
  pthread_mutex_t mutex;
} HarnessAllocationDomain;

static int64_t allocation_domain_live_count;

void *harness_allocation_domain_open(void) {
  HarnessAllocationDomain *domain = calloc(1, sizeof(*domain));
  if (!domain) return NULL;
  if (pthread_mutex_init(&domain->mutex, NULL) != 0) {
    free(domain);
    return NULL;
  }
  __sync_add_and_fetch(&allocation_domain_live_count, 1);
  return domain;
}

void *harness_allocation_domain_alloc(void *opaque, int64_t size, int64_t alignment) {
  HarnessAllocationDomain *domain = opaque;
  HarnessAllocationNode *node = malloc(sizeof(*node));
  void *pointer = NULL;
  size_t requested = size > 0 ? (size_t)size : 1;
  if (!node || posix_memalign(&pointer, (size_t)(alignment < sizeof(void *) ? sizeof(void *) : alignment), requested) != 0) {
    free(node);
    return NULL;
  }
  node->pointer = pointer;
  pthread_mutex_lock(&domain->mutex);
  node->next = domain->head;
  domain->head = node;
  pthread_mutex_unlock(&domain->mutex);
  return pointer;
}

void *harness_allocation_domain_resize(void *opaque, void *pointer, int64_t old_size,
                                       int64_t new_size, int64_t alignment) {
  (void)old_size;
  HarnessAllocationDomain *domain = opaque;
  void *replacement = harness_allocation_domain_alloc(opaque, new_size, alignment);
  if (!replacement) return NULL;
  size_t copy_size = (size_t)(old_size < new_size ? old_size : new_size);
  if (pointer && copy_size) __builtin_memcpy(replacement, pointer, copy_size);
  pthread_mutex_lock(&domain->mutex);
  HarnessAllocationNode **cursor = &domain->head;
  while (*cursor && (*cursor)->pointer != pointer) cursor = &(*cursor)->next;
  if (*cursor) {
    HarnessAllocationNode *removed = *cursor;
    *cursor = removed->next;
    free(removed->pointer);
    free(removed);
  }
  pthread_mutex_unlock(&domain->mutex);
  return replacement;
}

int64_t harness_allocation_domain_free(void *opaque, void *pointer) {
  HarnessAllocationDomain *domain = opaque;
  pthread_mutex_lock(&domain->mutex);
  HarnessAllocationNode **cursor = &domain->head;
  while (*cursor && (*cursor)->pointer != pointer) cursor = &(*cursor)->next;
  if (*cursor) {
    HarnessAllocationNode *removed = *cursor;
    *cursor = removed->next;
    free(removed->pointer);
    free(removed);
  }
  pthread_mutex_unlock(&domain->mutex);
  return 0;
}

int64_t harness_allocation_domain_close(void *opaque) {
  HarnessAllocationDomain *domain = opaque;
  if (!domain) return 0;
  HarnessAllocationNode *node = domain->head;
  while (node) {
    HarnessAllocationNode *next = node->next;
    free(node->pointer);
    free(node);
    node = next;
  }
  pthread_mutex_destroy(&domain->mutex);
  free(domain);
  __sync_sub_and_fetch(&allocation_domain_live_count, 1);
  return 0;
}

int64_t harness_allocation_domain_live_count(void) {
  return __sync_add_and_fetch(&allocation_domain_live_count, 0);
}
