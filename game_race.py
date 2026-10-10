#!/usr/bin/env python3
"""ENEOS RACER - псевдо-3D аркадная гонка (pygame).
Управление: стрелки/WASD - руль/газ/тормоз, SHIFT - нитро,
P - пауза, M - звук, ENTER - старт/рестарт, ESC - выход.
SMOKE=1 в окружении - автотест без окна (300 кадров и выход).
"""
import array
import math
import os
import random
import sys

import pygame

SMOKE = os.environ.get('SMOKE') == '1'

# ---------- константы ----------
W, H = 960, 540
SEG_LEN = 200
RUMBLE = 3
LANES = 3
ROAD_W = 2100
CAM_H = 1050
FOV = 100
CAM_DEPTH = 1.0 / math.tan(math.radians(FOV) / 2)
PLAYER_Z = CAM_H * CAM_DEPTH
MAX_SPEED = SEG_LEN * 60
CENTRIFUGAL = 0.32
TOTAL_LAPS_TIME = 60
LAP_BONUS = 30

COLORS = {
    'sky_top': (25, 8, 60), 'sky_mid': (120, 30, 110), 'sky_bot': (255, 130, 60),
    'sun': (255, 210, 120),
    'light_road': (112, 112, 116), 'dark_road': (102, 102, 106),
    'light_grass': (38, 140, 60), 'dark_grass': (32, 124, 52),
    'light_rumble': (235, 235, 235), 'dark_rumble': (200, 40, 40),
    'lane': (240, 240, 240),
}

# ---------- звук (полностью процедурный) ----------
class Sfx:
    def __init__(self):
        self.ok = False
        self.muted = False
        self.chan = None
        self.bucket = -1
        try:
            pygame.mixer.pre_init(44100, -16, 1, 512)
            pygame.mixer.init()
            self.ok = True
        except Exception:
            self.ok = False
        if self.ok:
            try:
                self.chan = pygame.mixer.Channel(0)
                self.fx = pygame.mixer.Channel(1)
            except Exception:
                self.ok = False

    def _pcm(self, samples):
        buf = array.array('h')
        for s in samples:
            v = max(-1.0, min(1.0, s))
            buf.append(int(v * 32767))
        return buf.tobytes()

    def engine(self, rpm01, on):
        if not self.ok:
            return
        if self.muted or not on:
            if self.chan.get_busy():
                self.chan.stop()
            self.bucket = -1
            return
        b = int(max(0.0, min(1.0, rpm01)) * 12)
        if b == self.bucket and self.chan.get_busy():
            return
        self.bucket = b
        freq = 55 + b * 14
        n = 11025
        out = []
        for i in range(n):
            t = i / 44100.0
            ph = (t * freq) % 1.0
            saw = ph * 2.0 - 1.0
            s = saw * 0.45 + 0.18 * math.sin(2 * math.pi * 2 * freq * t)
            out.append(s * 0.5)
        snd = pygame.mixer.Sound(buffer=self._pcm(out))
        snd.set_volume(0.22)
        self.chan.play(snd, loops=-1)

    def blip(self, freq=880, dur=0.12, vol=0.3):
        if not self.ok or self.muted:
            return
        n = int(44100 * dur)
        out = [math.sin(2 * math.pi * freq * i / 44100.0) * 0.6 for i in range(n)]
        snd = pygame.mixer.Sound(buffer=self._pcm(out))
        snd.set_volume(vol)
        self.fx.play(snd)

    def crash(self):
        if not self.ok or self.muted:
            return
        rnd = random.Random(7)
        n = int(44100 * 0.35)
        out = [(rnd.random() * 2.0 - 1.0) * (1.0 - i / n) * 0.7 for i in range(n)]
        snd = pygame.mixer.Sound(buffer=self._pcm(out))
        snd.set_volume(0.4)
        self.fx.play(snd)


# ---------- трасса ----------
class Segment:
    __slots__ = ('index', 'curve', 'y1', 'y2', 'sprites', 'line')
    def __init__(self, index, curve, y1, y2):
        self.index = index
        self.curve = curve
        self.y1 = y1
        self.y2 = y2
        self.sprites = []
        self.line = False


def build_track():
    segs = []
    y = 0.0

    def add_road(enter, hold, leave, curve, dy):
        nonlocal y
        total = enter + hold + leave
        for n in range(total):
            if n < enter:
                c = curve * n / max(1, enter)
                dyy = dy * n / max(1, enter)
            elif n < enter + hold:
                c = curve
                dyy = dy
            else:
                k = (n - enter - hold) / max(1, leave)
                c = curve * (1 - k)
                dyy = dy * (1 - k)
            y1 = y
            y += dyy
            segs.append(Segment(len(segs), c, y1, y))

    add_road(40, 40, 40, 0, 0)
    add_road(30, 30, 30, 2, 0)
    add_road(25, 25, 25, -3, 20)
    add_road(30, 20, 30, 0, -30)
    add_road(35, 25, 35, 4, 10)
    add_road(25, 25, 25, -2, 0)
    add_road(40, 30, 40, -5, -10)
    add_road(30, 30, 30, 3, 25)
    add_road(50, 40, 50, 0, 0)
    segs[0].line = True
    # обочины: деревья, кусты и фонари
    rnd = random.Random(42)
    for i, s in enumerate(segs):
        if i % 4 == 0:
            side = 1 if (i // 4) % 2 == 0 else -1
            r = rnd.random()
            kind = 'tree' if r < 0.55 else ('bush' if r < 0.85 else 'lamp')
            s.sprites.append((side * (1.6 + rnd.random() * 1.6), kind))
        if i % 11 == 5:
            s.sprites.append((-1.7 - rnd.random(), 'tree'))
    return segs


# ---------- спрайты (рисуем кодом один раз) ----------
def make_player(color_body=(200, 30, 40)):
    surf = pygame.Surface((200, 110), pygame.SRCALPHA)
    # тень
    pygame.draw.ellipse(surf, (0, 0, 0, 110), (20, 88, 160, 16))
    # колеса
    for wx in (28, 152):
        pygame.draw.rect(surf, (12, 12, 14), (wx, 62, 20, 34), border_radius=5)
    # кузов - черный маслкар
    pygame.draw.rect(surf, (22, 22, 28), (30, 40, 140, 52), border_radius=12)
    pygame.draw.rect(surf, (255, 255, 255, 40), (30, 40, 140, 10), border_radius=6)
    # белые гоночные полосы
    pygame.draw.rect(surf, (235, 235, 240), (88, 40, 10, 52))
    pygame.draw.rect(surf, (235, 235, 240), (102, 40, 10, 52))
    # кабина и стекло
    pygame.draw.rect(surf, (18, 18, 24), (62, 22, 76, 34), border_radius=10)
    pygame.draw.rect(surf, (120, 170, 210), (68, 26, 64, 22), border_radius=7)
    pygame.draw.rect(surf, (235, 235, 240), (94, 26, 4, 22))
    pygame.draw.rect(surf, (235, 235, 240), (102, 26, 4, 22))
    # хром-бампер
    pygame.draw.rect(surf, (170, 175, 185), (34, 82, 132, 8), border_radius=4)
    # задняя световая полоса
    pygame.draw.rect(surf, (255, 45, 45), (40, 64, 120, 12), border_radius=5)
    pygame.draw.rect(surf, (255, 140, 140), (40, 64, 120, 4), border_radius=2)
    # номер
    pygame.draw.rect(surf, (240, 200, 60), (86, 78, 28, 10), border_radius=2)
    # выхлоп
    pygame.draw.circle(surf, (40, 40, 44), (66, 92), 6)
    pygame.draw.circle(surf, (40, 40, 44), (134, 92), 6)
    return surf


def make_traffic(color_body):
    surf = pygame.Surface((150, 84), pygame.SRCALPHA)
    pygame.draw.ellipse(surf, (0, 0, 0, 100), (15, 68, 120, 12))
    for wx in (22, 114):
        pygame.draw.rect(surf, (12, 12, 14), (wx, 48, 16, 26), border_radius=4)
    pygame.draw.rect(surf, color_body, (24, 30, 102, 40), border_radius=10)
    pygame.draw.rect(surf, (25, 25, 35), (46, 14, 58, 26), border_radius=8)
    pygame.draw.rect(surf, (140, 200, 235), (51, 17, 48, 16), border_radius=6)
    pygame.draw.rect(surf, (255, 220, 120), (28, 50, 20, 8), border_radius=3)
    pygame.draw.rect(surf, (255, 220, 120), (102, 50, 20, 8), border_radius=3)
    return surf


def make_tree():
    surf = pygame.Surface((90, 130), pygame.SRCALPHA)
    pygame.draw.rect(surf, (90, 60, 35), (40, 90, 10, 36))
    pygame.draw.polygon(surf, (20, 110, 40), [(45, 0), (8, 70), (82, 70)])
    pygame.draw.polygon(surf, (28, 132, 52), [(45, 30), (14, 95), (76, 95)])
    return surf


def make_lamp():
    surf = pygame.Surface((40, 150), pygame.SRCALPHA)
    pygame.draw.rect(surf, (60, 60, 66), (17, 20, 6, 126))
    pygame.draw.rect(surf, (60, 60, 66), (17, 20, 30, 6))
    pygame.draw.circle(surf, (255, 230, 150), (44, 30), 7)
    pygame.draw.circle(surf, (255, 230, 150, 90), (44, 30), 13, 2)
    return surf


def make_bush(seed=1):
    rnd = random.Random(seed)
    surf = pygame.Surface((110, 70), pygame.SRCALPHA)
    cols = [(200, 90, 30), (170, 60, 25), (215, 130, 40), (150, 50, 60)]
    for _ in range(7):
        x = rnd.randint(15, 95)
        y = rnd.randint(20, 55)
        r = rnd.randint(10, 20)
        pygame.draw.circle(surf, rnd.choice(cols), (x, y), r)
    return surf


# ---------- игра ----------
class Game:
    def __init__(self):
        if SMOKE:
            os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
            os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption('ENEOS RACER')
        self.clock = pygame.time.Clock()
        self.font_big = pygame.font.SysFont(None, 64)
        self.font = pygame.font.SysFont(None, 30)
        self.font_small = pygame.font.SysFont(None, 22)
        self.sfx = Sfx()
        self.segs = build_track()
        self.track_len = len(self.segs) * SEG_LEN
        self.player_img = make_player()
        self.traffic_imgs = [make_traffic(c) for c in
                             [(30, 120, 220), (240, 200, 40), (40, 200, 120),
                              (200, 40, 180), (230, 230, 235), (255, 120, 30)]]
        self.tree_img = make_tree()
        self.lamp_img = make_lamp()
        self.best = self.load_best()
        self.reset()
        self.frame = 0

    def base_dir(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def load_best(self):
        try:
            with open(os.path.join(self.base_dir(), 'eneos_best.txt')) as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def save_best(self):
        try:
            with open(os.path.join(self.base_dir(), 'eneos_best.txt'), 'w') as f:
                f.write(str(self.best))
        except Exception:
            pass

    def reset(self):
        self.pos = 0.0
        self.speed = 0.0
        self.player_x = 0.0
        self.time = float(TOTAL_LAPS_TIME)
        self.score = 0
        self.state = 'menu' if not SMOKE else 'countdown'
        self.countdown = 3.2 if not SMOKE else 0.3
        self.msg = ''
        self.msg_t = 0.0
        self.nitro = 100.0
        self.shake = 0.0
        self.offroad = False
        rnd = random.Random(99)
        self.cars = []
        for i in range(14):
            self.cars.append({
                'z': rnd.random() * self.track_len,
                'off': rnd.choice([-0.75, 0.0, 0.75]) + rnd.uniform(-0.1, 0.1),
                'speed': MAX_SPEED * rnd.uniform(0.35, 0.62),
                'img': i % len(self.traffic_imgs),
            })

    # ----- проекция -----
    def project(self, world_x, world_y, world_z, cam_x, cam_y, cam_z):
        cz = world_z - cam_z
        if cz <= 1:
            cz = 1
        scale = CAM_DEPTH / cz
        return (W / 2 + scale * (world_x - cam_x) * W / 2,
                H / 2 - scale * (world_y - cam_y) * H / 2,
                scale)

    def poly(self, x1, y1, x2, y2, x3, y3, x4, y4, color):
        pygame.draw.polygon(self.screen, color,
                            [(x1, y1), (x2, y2), (x3, y3), (x4, y4)])

    # ----- отрисовка кадра -----
    def render(self):
        base_i = int(self.pos / SEG_LEN) % len(self.segs)
        base_pct = (self.pos % SEG_LEN) / SEG_LEN
        player_seg = self.segs[base_i]
        player_pct = base_pct
        player_y = player_seg.y1 + (player_seg.y2 - player_seg.y1) * player_pct

        self.screen.fill(COLORS['sky_top'])
        self.draw_sky()
        self.draw_mountains(base_i)

        # проход 1: ближние -> дальние, считаем проекции
        comp = []
        camx_map = {}
        x = 0.0
        dx = -(player_seg.curve * player_pct)
        for n in range(180):
            i = (base_i + n) % len(self.segs)
            s = self.segs[i]
            looped = i < base_i
            cam_z = self.pos - (self.track_len if looped else 0)
            z_near = s.index * SEG_LEN - cam_z
            camx = self.player_x * ROAD_W - x
            if z_near + SEG_LEN <= 10:
                comp.append(None)
            else:
                x1, y1, sc1 = self.project(0, player_y, z_near, camx, CAM_H + player_y, 0)
                x2, y2, sc2 = self.project(0, player_y, z_near + SEG_LEN,
                                           self.player_x * ROAD_W - x - dx, CAM_H + player_y, 0)
                comp.append((s, x1, y1, sc1, x2, y2, sc2, camx, z_near))
                camx_map[i] = camx
            x += dx
            dx += s.curve

        # проход 2: дальние -> ближние, рисуем (художник: кто дальше, тот раньше)
        for n in range(179, -1, -1):
            c = comp[n]
            if c is None:
                continue
            s, x1, y1, sc1, x2, y2, sc2, camx, z_near = c
            if y1 < 0 and y2 < 0:
                continue
            if y1 > H + 400 and y2 > H + 400:
                continue
            self.render_segment(s, x1, y1, sc1, x2, y2, sc2)
            for off, kind in s.sprites:
                sx, sy, ssc = self.project(off * ROAD_W, player_y, z_near,
                                           camx, CAM_H + player_y, 0)
                if sy < 0 or sy > H + 60:
                    continue
                img = self.tree_img if kind == 'tree' else self.lamp_img
                w = max(2, int(img.get_width() * ssc * W / 2 * 0.9))
                h = max(2, int(img.get_height() * ssc * W / 2 * 0.9))
                if w > 4 and h > 4 and sx > -w and sx < W + w:
                    self.screen.blit(pygame.transform.smoothscale(img, (w, h)),
                                     (sx - w / 2, sy - h))

        runners = []
        for car in self.cars:
            rel = (car['z'] - self.pos) % self.track_len
            if rel < SEG_LEN * 2 or rel > SEG_LEN * 170:
                continue
            ci = int(car['z'] / SEG_LEN) % len(self.segs)
            if ci not in camx_map:
                continue
            runners.append((rel, car, camx_map[ci]))
        for rel, car, camx in sorted(runners, key=lambda r: -r[0]):
            cx, cy, csc = self.project(car['off'] * ROAD_W, player_y, rel,
                                       camx, CAM_H + player_y, 0)
            img = self.traffic_imgs[car['img']]
            w = max(4, int(150 * csc * W / 2))
            h = max(3, int(84 * csc * W / 2))
            if w > 900 or cy < -40 or cy > H + 60:
                continue
            if cx > -w and cx < W + w:
                self.screen.blit(pygame.transform.smoothscale(img, (w, h)),
                                 (cx - w / 2, cy - h))

        self.draw_player()
        self.draw_hud()

    def render_segment(self, s, x1, y1, sc1, x2, y2, sc2):
        r1 = int(ROAD_W * sc1 * W / 2)
        r2 = int(ROAD_W * sc2 * W / 2)
        l1 = int(ROAD_W * 0.14 * sc1 * W / 2)
        l2 = int(ROAD_W * 0.14 * sc2 * W / 2)
        lane1 = int(ROAD_W * 0.02 * sc1 * W / 2)
        lane2 = int(ROAD_W * 0.02 * sc2 * W / 2)
        dark = (s.index // RUMBLE) % 2 == 0
        grass = COLORS['dark_grass'] if dark else COLORS['light_grass']
        rumble = COLORS['dark_rumble'] if dark else COLORS['light_rumble']
        road = COLORS['dark_road'] if dark else COLORS['light_road']
        self.poly(0, y1, W, y1, W, y2, 0, y2, grass)
        self.poly(x1 - r1 - l1, y1, x1 + r1 + l1, y1,
                  x2 + r2 + l2, y2, x2 - r2 - l2, y2, rumble)
        self.poly(x1 - r1, y1, x1 + r1, y1, x2 + r2, y2, x2 - r2, y2, road)
        if s.line:
            for k in range(6):
                lx1 = x1 - r1 + (2 * r1) * k / 6
                lx2 = x2 - r2 + (2 * r2) * k / 6
                c = (255, 255, 255) if k % 2 == 0 else (20, 20, 20)
                self.poly(lx1, y1, lx1 + (2 * r1) / 6, y1,
                          lx2 + (2 * r2) / 6, y2, lx2, y2, c)
        elif dark:
            for lane in range(1, LANES):
                lx1 = x1 - r1 + (2 * r1) * lane / LANES
                lx2 = x2 - r2 + (2 * r2) * lane / LANES
                self.poly(lx1 - lane1 / 2, y1, lx1 + lane1 / 2, y1,
                          lx2 + lane2 / 2, y2, lx2 - lane2 / 2, y2, COLORS['lane'])

    def draw_sky(self):
        for i in range(24):
            t = i / 24.0
            r = int(COLORS['sky_top'][0] + (COLORS['sky_bot'][0] - COLORS['sky_top'][0]) * t)
            g = int(COLORS['sky_top'][1] + (COLORS['sky_bot'][1] - COLORS['sky_top'][1]) * t)
            b = int(COLORS['sky_top'][2] + (COLORS['sky_bot'][2] - COLORS['sky_top'][2]) * t)
            pygame.draw.rect(self.screen, (r, g, b), (0, int(H * 0.42 * i / 24), W, int(H * 0.42 / 24) + 1))
        pygame.draw.circle(self.screen, (255, 160, 90), (W // 2 + 180, int(H * 0.30)), 46)
        pygame.draw.circle(self.screen, COLORS['sun'], (W // 2 + 180, int(H * 0.30)), 34)

    def draw_mountains(self, base_i):
        for layer, (color, amp, base, period) in enumerate([
                ((60, 20, 90), 40, H * 0.42, 0.05),
                ((40, 14, 70), 60, H * 0.44, 0.031)]):
            pts = [(0, base + 20)]
            shift = (self.pos / SEG_LEN * (1 + layer)) % 200
            for x in range(0, W + 20, 20):
                y = base - abs(math.sin((x + shift * 8) * period)) * amp
                pts.append((x, y))
            pts.append((W, base + 20))
            pygame.draw.polygon(self.screen, color, pts)

    def draw_player(self):
        img = self.player_img
        w, h = 230, 126
        sx = W / 2
        if self.shake > 0:
            sx += random.uniform(-1, 1) * self.shake * 14
        sy = H - 24
        keys = pygame.key.get_pressed()
        lean = 0
        if not SMOKE:
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                lean = -1
            elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                lean = 1
        else:
            lean = 1 if (self.frame // 60) % 2 == 0 else -1
        self.screen.blit(pygame.transform.smoothscale(img, (w, h)), (sx - w / 2 + lean * 8, sy - h))
        if self.speed > MAX_SPEED * 0.92:
            # нитро-пламя
            for i, fx in enumerate((-24, 24)):
                fl = 14 + random.uniform(0, 14)
                pygame.draw.polygon(self.screen, (120, 200, 255),
                                    [(sx + fx - 7, sy - 22), (sx + fx + 7, sy - 22),
                                     (sx + fx, sy - 22 + fl)])
                pygame.draw.polygon(self.screen, (255, 240, 180),
                                    [(sx + fx - 4, sy - 22), (sx + fx + 4, sy - 22),
                                     (sx + fx, sy - 22 + fl * 0.6)])

    def draw_hud(self):
        kmh = int(self.speed / MAX_SPEED * 320)
        txt = self.font_big.render(str(kmh), True, (255, 255, 255))
        self.screen.blit(txt, (W - 20 - txt.get_width(), H - 116))
        lbl = self.font_small.render('km/h', True, (220, 220, 220))
        self.screen.blit(lbl, (W - 20 - lbl.get_width(), H - 58))
        t = self.font.render('TIME %d' % int(max(0, self.time)), True,
                             (255, 80, 80) if self.time < 10 else (255, 255, 255))
        self.screen.blit(t, (W / 2 - t.get_width() / 2, 12))
        s = self.font.render('SCORE %d' % self.score, True, (255, 235, 150))
        self.screen.blit(s, (16, 12))
        b = self.font_small.render('BEST %d' % max(self.best, self.score), True, (200, 200, 200))
        self.screen.blit(b, (16, 44))
        # нитро-полоса слева внизу
        nl = self.font_small.render('NITRO [SHIFT]', True, (150, 200, 255))
        self.screen.blit(nl, (16, H - 58))
        pygame.draw.rect(self.screen, (20, 20, 30), (16, H - 34, 214, 14), border_radius=7)
        nw = int(210 * max(0.0, min(1.0, self.nitro / 100.0)))
        pygame.draw.rect(self.screen, (80, 180, 255), (18, H - 32, nw, 10), border_radius=5)
        if self.offroad and self.speed > MAX_SPEED * 0.2:
            w = self.font.render('OFFROAD!', True, (255, 200, 80))
            self.screen.blit(w, (W / 2 - w.get_width() / 2, 60))
        if self.msg_t > 0:
            m = self.font.render(self.msg, True, (140, 255, 160))
            self.screen.blit(m, (W / 2 - m.get_width() / 2, 96))

    def draw_menu(self):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((8, 4, 24, 190))
        self.screen.blit(ov, (0, 0))
        t = self.font_big.render('ENEOS RACER', True, (255, 200, 90))
        self.screen.blit(t, (W / 2 - t.get_width() / 2, 120))
        lines = ['ENTER - start', 'Arrows / WASD - drive', 'SHIFT - nitro',
                 'P - pause, M - sound', 'Reach the line in time: +30s per lap']
        for i, ln in enumerate(lines):
            s = self.font.render(ln, True, (230, 230, 240))
            self.screen.blit(s, (W / 2 - s.get_width() / 2, 220 + i * 36))
        if int(self.frame / 30) % 2 == 0:
            p = self.font.render('Press ENTER', True, (140, 255, 160))
            self.screen.blit(p, (W / 2 - p.get_width() / 2, 440))

    def draw_countdown(self):
        n = int(math.ceil(self.countdown))
        t = self.font_big.render(str(max(1, n)), True, (255, 255, 255))
        self.screen.blit(t, (W / 2 - t.get_width() / 2, H / 2 - 80))

    def draw_over(self):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((8, 4, 24, 200))
        self.screen.blit(ov, (0, 0))
        t = self.font_big.render('TIME UP', True, (255, 90, 90))
        self.screen.blit(t, (W / 2 - t.get_width() / 2, 140))
        s = self.font.render('SCORE %d   BEST %d' % (self.score, max(self.best, self.score)),
                             True, (255, 235, 150))
        self.screen.blit(s, (W / 2 - s.get_width() / 2, 230))
        p = self.font.render('ENTER - restart', True, (140, 255, 160))
        self.screen.blit(p, (W / 2 - p.get_width() / 2, 300))

    # ----- логика -----
    def update(self, dt):
        keys = pygame.key.get_pressed()
        if SMOKE:
            gas, brake, left, right, nitro = True, False, (self.frame // 60) % 2 == 0, (self.frame // 60) % 2 == 1, (self.frame % 200) < 60
        else:
            gas = keys[pygame.K_UP] or keys[pygame.K_w]
            brake = keys[pygame.K_DOWN] or keys[pygame.K_s]
            left = keys[pygame.K_LEFT] or keys[pygame.K_a]
            right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
            nitro = (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and self.nitro > 0

        if self.state == 'menu':
            self.sfx.engine(0, False)
            return
        if self.state == 'countdown':
            self.countdown -= dt
            if self.countdown <= 0:
                self.state = 'race'
            return
        if self.state == 'over':
            self.sfx.engine(0, False)
            return
        if self.state == 'pause':
            self.sfx.engine(0, False)
            return

        # скорость
        target = MAX_SPEED
        if nitro and gas:
            target = MAX_SPEED * 1.35
            self.nitro = max(0.0, self.nitro - 30 * dt)
        else:
            self.nitro = min(100.0, self.nitro + 6 * dt)
        if gas:
            self.speed += (target - self.speed) * min(1.0, 1.6 * dt)
        elif brake:
            self.speed -= MAX_SPEED * 1.4 * dt
        else:
            self.speed -= MAX_SPEED * 0.25 * dt
        self.speed = max(0.0, min(MAX_SPEED * 1.35, self.speed))

        # руль + центробежная
        base_i = int(self.pos / SEG_LEN) % len(self.segs)
        steer = 0.0
        if left:
            steer -= 1.0
        if right:
            steer += 1.0
        dx = dt * 2.2 * (self.speed / MAX_SPEED)
        self.player_x += steer * dx
        self.player_x -= dx * self.speed / MAX_SPEED * self.segs[base_i].curve * CENTRIFUGAL * 0.4

        # обочина
        self.offroad = abs(self.player_x) > 1.05
        if self.offroad and self.speed > MAX_SPEED * 0.35:
            self.speed -= MAX_SPEED * 0.9 * dt
        self.player_x = max(-2.2, min(2.2, self.player_x))

        # движение
        prev_lap = self.pos / self.track_len
        self.pos = (self.pos + self.speed * dt) % self.track_len
        if self.pos / self.track_len < prev_lap and self.speed > MAX_SPEED * 0.3:
            self.time += LAP_BONUS
            self.msg = 'CHECKPOINT +%ds' % LAP_BONUS
            self.msg_t = 2.0
            self.sfx.blip(880)
        self.score = int(self.score + self.speed * dt / SEG_LEN)
        self.time -= dt
        if self.msg_t > 0:
            self.msg_t -= dt
        if self.shake > 0:
            self.shake -= dt

        # трафик
        for car in self.cars:
            car['z'] = (car['z'] + car['speed'] * dt) % self.track_len
            # не давать въезжать друг в друга
            for o in self.cars:
                if o is car:
                    continue
                gap = (o['z'] - car['z']) % self.track_len
                if 0 < gap < SEG_LEN * 4 and abs(o['off'] - car['off']) < 0.4:
                    car['speed'] = min(car['speed'], o['speed'])

        # столкновения
        for car in self.cars:
            rel = (car['z'] - self.pos) % self.track_len
            if rel < SEG_LEN * 3 and abs(car['off'] - self.player_x) < 0.42:
                if self.speed > car['speed'] + MAX_SPEED * 0.1:
                    self.speed = car['speed'] * 0.5
                    self.shake = 0.6
                    self.msg = 'CRASH!'
                    self.msg_t = 1.2
                    self.sfx.crash()

        if self.time <= 0:
            self.time = 0
            self.state = 'over'
            if self.score > self.best:
                self.best = self.score
                self.save_best()

        self.sfx.engine(self.speed / (MAX_SPEED * 1.35),
                        self.state == 'race' and self.speed > 1)

    def run(self):
        frames = 0
        while True:
            dt = min(0.05, self.clock.tick(60) / 1000.0)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    return
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        pygame.quit()
                        return
                    if SMOKE:
                        continue
                    if ev.key == pygame.K_RETURN or ev.key == pygame.K_KP_ENTER:
                        if self.state in ('menu', 'over'):
                            self.reset()
                            self.state = 'countdown'
                            self.countdown = 3.2
                    if ev.key == pygame.K_p:
                        if self.state == 'race':
                            self.state = 'pause'
                        elif self.state == 'pause':
                            self.state = 'race'
                    if ev.key == pygame.K_m:
                        self.sfx.muted = not self.sfx.muted
            if not SMOKE and self.state == 'menu' and pygame.key.get_pressed()[pygame.K_RETURN]:
                pass
            self.update(dt)
            if self.state == 'menu':
                self.render()
                self.draw_menu()
            elif self.state == 'countdown':
                self.render()
                self.draw_countdown()
            elif self.state == 'over':
                self.render()
                self.draw_over()
            elif self.state == 'pause':
                self.render()
                p = self.font_big.render('PAUSE', True, (255, 255, 255))
                self.screen.blit(p, (W / 2 - p.get_width() / 2, H / 2 - 40))
            else:
                self.render()
            pygame.display.flip()
            self.frame += 1
            frames += 1
            if SMOKE and frames >= 400:
                print('SMOKE OK dist=%d score=%d state=%s' % (int(self.pos), self.score, self.state))
                pygame.quit()
                return


if __name__ == '__main__':
    Game().run()
