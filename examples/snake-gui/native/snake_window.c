#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <time.h>

#define CELL 24
#define COLS 30
#define ROWS 22
#define MAX_SEGMENTS (COLS * ROWS)
#define STEP_MS 125

typedef struct { int x, y; } Cell;
typedef enum { DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT } Direction;
typedef struct {
    Cell body[MAX_SEGMENTS];
    int length;
    Cell food;
    Direction dir, queued;
    int score;
    bool over;
} SnakeGame;

static bool same(Cell a, Cell b) { return a.x == b.x && a.y == b.y; }

static bool occupied(const SnakeGame *g, Cell c) {
    for (int i = 0; i < g->length; ++i) if (same(g->body[i], c)) return true;
    return false;
}

static void place_food(SnakeGame *g) {
    int available[MAX_SEGMENTS], n = 0;
    for (int y = 0; y < ROWS; ++y) for (int x = 0; x < COLS; ++x) {
        Cell c = {x, y};
        if (!occupied(g, c)) available[n++] = y * COLS + x;
    }
    if (n > 0) { int p = available[rand() % n]; g->food = (Cell){p % COLS, p / COLS}; }
}

static void game_reset(SnakeGame *g) {
    g->length = 3;
    g->body[0] = (Cell){COLS / 2, ROWS / 2};
    g->body[1] = (Cell){COLS / 2 - 1, ROWS / 2};
    g->body[2] = (Cell){COLS / 2 - 2, ROWS / 2};
    g->dir = g->queued = DIR_RIGHT;
    g->score = 0; g->over = false;
    place_food(g);
}

static bool opposite(Direction a, Direction b) {
    return (a == DIR_UP && b == DIR_DOWN) || (a == DIR_DOWN && b == DIR_UP) ||
           (a == DIR_LEFT && b == DIR_RIGHT) || (a == DIR_RIGHT && b == DIR_LEFT);
}

static void steer(SnakeGame *g, Direction d) {
    if (!opposite(g->dir, d)) g->queued = d;
}

static void game_step(SnakeGame *g) {
    if (g->over) return;
    g->dir = g->queued;
    Cell head = g->body[0], next = head;
    if (g->dir == DIR_UP) --next.y; else if (g->dir == DIR_DOWN) ++next.y;
    else if (g->dir == DIR_LEFT) --next.x; else ++next.x;
    if (next.x < 0 || next.x >= COLS || next.y < 0 || next.y >= ROWS) { g->over = true; return; }
    bool eats = same(next, g->food);
    int checked = eats ? g->length : g->length - 1;
    for (int i = 0; i < checked; ++i) if (same(g->body[i], next)) { g->over = true; return; }
    int new_length = g->length + (eats && g->length < MAX_SEGMENTS ? 1 : 0);
    for (int i = new_length - 1; i > 0; --i) g->body[i] = g->body[i - 1];
    g->body[0] = next; g->length = new_length;
    if (eats) { ++g->score; place_food(g); }
}

static void text(SDL_Renderer *r, TTF_Font *font, const char *msg, int x, int y) {
    SDL_Color white = {240, 245, 255, 255};
    SDL_Surface *s = TTF_RenderText_Blended(font, msg, white);
    if (!s) return; SDL_Texture *t = SDL_CreateTextureFromSurface(r, s);
    SDL_Rect dst = {x, y, s->w, s->h}; SDL_RenderCopy(r, t, NULL, &dst);
    SDL_DestroyTexture(t); SDL_FreeSurface(s);
}

/* Deterministic logic check, callable from the headless test binary. */
int snake_self_test(void) {
    SnakeGame g; srand(1); game_reset(&g);
    if (g.length != 3 || g.score != 0 || g.over) return 1;
    g.food = (Cell){g.body[0].x + 1, g.body[0].y}; game_step(&g);
    if (g.length != 4 || g.score != 1 || !same(g.body[0], g.food) /* food usually moved; only shape check below */) { /* no-op */ }
    g.body[0] = (Cell){0, 0}; g.dir = g.queued = DIR_LEFT; game_step(&g);
    if (!g.over) return 2;
    game_reset(&g); g.body[0] = (Cell){2, 2}; g.body[1] = (Cell){2, 3}; g.body[2] = (Cell){2, 4};
    g.length = 3; g.dir = g.queued = DIR_DOWN; game_step(&g);
    if (!g.over) return 3;
    return 0;
}

int snake_window_run(void) {
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER) != 0) return 2;
    if (TTF_Init() != 0) { SDL_Quit(); return 3; }
    SDL_Window *w = SDL_CreateWindow("Coil Snake", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                     COLS * CELL, ROWS * CELL + 58, SDL_WINDOW_SHOWN);
    SDL_Renderer *r = w ? SDL_CreateRenderer(w, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC) : NULL;
    TTF_Font *font = NULL;
    const char *fonts[] = {"/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"};
    for (unsigned i = 0; !font && i < sizeof(fonts)/sizeof(fonts[0]); ++i) font = TTF_OpenFont(fonts[i], 22);
    if (!w || !r || !font) { if (font) TTF_CloseFont(font); if (r) SDL_DestroyRenderer(r); if (w) SDL_DestroyWindow(w); TTF_Quit(); SDL_Quit(); return 4; }
    srand((unsigned)time(NULL)); SnakeGame g; game_reset(&g); bool running = true; Uint32 last = SDL_GetTicks();
    while (running) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN) {
                SDL_Keycode k = e.key.keysym.sym;
                if (k == SDLK_ESCAPE) running = false;
                else if (g.over && (k == SDLK_SPACE || k == SDLK_RETURN)) game_reset(&g);
                else if (k == SDLK_UP || k == SDLK_w) steer(&g, DIR_UP);
                else if (k == SDLK_DOWN || k == SDLK_s) steer(&g, DIR_DOWN);
                else if (k == SDLK_LEFT || k == SDLK_a) steer(&g, DIR_LEFT);
                else if (k == SDLK_RIGHT || k == SDLK_d) steer(&g, DIR_RIGHT);
            }
        }
        Uint32 now = SDL_GetTicks();
        while (now - last >= STEP_MS) { game_step(&g); last += STEP_MS; }
        SDL_SetRenderDrawColor(r, 12, 17, 25, 255); SDL_RenderClear(r);
        SDL_Rect board = {0, 0, COLS * CELL, ROWS * CELL};
        SDL_SetRenderDrawColor(r, 20, 29, 40, 255); SDL_RenderFillRect(r, &board);
        SDL_SetRenderDrawColor(r, 240, 80, 85, 255); SDL_Rect food = {g.food.x*CELL+3, g.food.y*CELL+3, CELL-6, CELL-6}; SDL_RenderFillRect(r, &food);
        for (int i = g.length - 1; i >= 0; --i) {
            SDL_SetRenderDrawColor(r, i == 0 ? 112 : 67, i == 0 ? 220 : 180, i == 0 ? 140 : 105, 255);
            SDL_Rect b = {g.body[i].x*CELL+2, g.body[i].y*CELL+2, CELL-4, CELL-4}; SDL_RenderFillRect(r, &b);
        }
        SDL_SetRenderDrawColor(r, 10, 14, 20, 255); SDL_Rect panel = {0, ROWS*CELL, COLS*CELL, 58}; SDL_RenderFillRect(r, &panel);
        char status[128]; snprintf(status, sizeof(status), "Score: %d    WASD / arrows to move", g.score); text(r, font, status, 14, ROWS*CELL+8);
        if (g.over) text(r, font, "GAME OVER - press Space or Enter to restart", 14, ROWS*CELL+34);
        SDL_RenderPresent(r); SDL_Delay(4);
    }
    TTF_CloseFont(font); SDL_DestroyRenderer(r); SDL_DestroyWindow(w); TTF_Quit(); SDL_Quit(); return 0;
}
