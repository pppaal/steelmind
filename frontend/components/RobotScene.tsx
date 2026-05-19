"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { RobotState, SensorData } from "@/lib/types";
import { STATE_COLORS } from "@/lib/types";

interface Props {
  state: RobotState;
  sensor: SensorData | null;
}

interface Rig {
  group: THREE.Group;
  parts: THREE.Mesh[];
  joints: {
    hipLeft: THREE.Group;
    hipRight: THREE.Group;
    kneeLeft: THREE.Group;
    kneeRight: THREE.Group;
    shoulderLeft: THREE.Group;
    shoulderRight: THREE.Group;
  };
}

function buildRig(): Rig {
  const group = new THREE.Group();
  const parts: THREE.Mesh[] = [];
  const makeMat = () =>
    new THREE.MeshStandardMaterial({ color: STATE_COLORS.IDLE, metalness: 0.3, roughness: 0.5 });

  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.0, 0.4), makeMat());
  torso.position.y = 1.6;
  parts.push(torso);
  group.add(torso);

  const head = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), makeMat());
  head.position.y = 2.35;
  parts.push(head);
  group.add(head);

  // Face: visor strip + two eyes — sit slightly proud of the front (+Z) face.
  const visor = new THREE.Mesh(
    new THREE.BoxGeometry(0.32, 0.08, 0.02),
    new THREE.MeshStandardMaterial({ color: 0x0a0f1c, roughness: 0.2, metalness: 0.6, emissive: 0x111827 }),
  );
  visor.position.set(0, 0.04, 0.21);
  head.add(visor);

  const eyeMat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    emissive: 0x60a5fa,
    emissiveIntensity: 0.9,
    roughness: 0.4,
  });
  const eyeL = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.05, 0.02), eyeMat);
  eyeL.position.set(-0.08, 0.04, 0.215);
  const eyeR = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.05, 0.02), eyeMat);
  eyeR.position.set(0.08, 0.04, 0.215);
  head.add(eyeL);
  head.add(eyeR);

  const makeLimbSegment = (
    parent: THREE.Object3D,
    pivot: THREE.Vector3,
    size: [number, number, number],
    offsetY: number,
  ): { joint: THREE.Group; mesh: THREE.Mesh } => {
    const joint = new THREE.Group();
    joint.position.copy(pivot);
    parent.add(joint);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), makeMat());
    mesh.position.y = offsetY;
    joint.add(mesh);
    parts.push(mesh);
    return { joint, mesh };
  };

  // Arms (shoulder pivots on torso)
  const shoulderLeft = makeLimbSegment(torso, new THREE.Vector3(0.45, 0.4, 0), [0.2, 0.8, 0.2], -0.4).joint;
  const shoulderRight = makeLimbSegment(torso, new THREE.Vector3(-0.45, 0.4, 0), [0.2, 0.8, 0.2], -0.4).joint;

  // Hips/legs (hip pivots at torso bottom, knees below)
  const hipLeftSeg = makeLimbSegment(torso, new THREE.Vector3(0.2, -0.5, 0), [0.25, 0.7, 0.25], -0.35);
  const hipRightSeg = makeLimbSegment(torso, new THREE.Vector3(-0.2, -0.5, 0), [0.25, 0.7, 0.25], -0.35);

  const kneeLeftSeg = makeLimbSegment(hipLeftSeg.joint, new THREE.Vector3(0, -0.7, 0), [0.22, 0.7, 0.22], -0.35);
  const kneeRightSeg = makeLimbSegment(hipRightSeg.joint, new THREE.Vector3(0, -0.7, 0), [0.22, 0.7, 0.22], -0.35);

  // Feet
  const footL = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.1, 0.45), makeMat());
  footL.position.set(0, -0.75, 0.08);
  kneeLeftSeg.joint.add(footL);
  parts.push(footL);
  const footR = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.1, 0.45), makeMat());
  footR.position.set(0, -0.75, 0.08);
  kneeRightSeg.joint.add(footR);
  parts.push(footR);

  return {
    group,
    parts,
    joints: {
      hipLeft: hipLeftSeg.joint,
      hipRight: hipRightSeg.joint,
      kneeLeft: kneeLeftSeg.joint,
      kneeRight: kneeRightSeg.joint,
      shoulderLeft,
      shoulderRight,
    },
  };
}

export default function RobotScene({ state, sensor }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<RobotState>(state);
  const sensorRef = useRef<SensorData | null>(sensor);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  useEffect(() => {
    sensorRef.current = sensor;
  }, [sensor]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0a0f1c");
    scene.fog = new THREE.Fog("#0a0f1c", 8, 24);

    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(3.5, 2.4, 4.5);
    camera.lookAt(0, 1.2, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 2;
    controls.maxDistance = 12;
    controls.maxPolarAngle = Math.PI / 2 - 0.05;
    controls.target.set(0, 1.2, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.3));
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(5, 9, 4);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -6;
    key.shadow.camera.right = 6;
    key.shadow.camera.top = 6;
    key.shadow.camera.bottom = -6;
    key.shadow.bias = -0.0005;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.7);
    rim.position.set(-4, 3, -3);
    scene.add(rim);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(40, 40),
      new THREE.MeshStandardMaterial({ color: 0x0b1220, roughness: 0.85, metalness: 0.15 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);

    const grid = new THREE.GridHelper(20, 20, 0x1e293b, 0x1e293b);
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.6;
    scene.add(grid);

    // Facing indicator: small arrow on the ground pointing along the robot's +Z.
    const arrow = new THREE.ArrowHelper(
      new THREE.Vector3(0, 0, 1),
      new THREE.Vector3(0, 0.02, 0),
      0.9,
      0x38bdf8,
      0.25,
      0.15,
    );
    scene.add(arrow);

    const rig = buildRig();
    rig.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        m.castShadow = true;
        m.receiveShadow = true;
      }
    });
    scene.add(rig.group);

    const clock = new THREE.Clock();
    let frame = 0;
    const targetColor = new THREE.Color(STATE_COLORS.IDLE);

    const onResize = () => {
      if (!mount) return;
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    const animate = () => {
      frame = requestAnimationFrame(animate);
      const t = clock.getElapsedTime();
      const s = stateRef.current;

      targetColor.set(STATE_COLORS[s]);
      for (const mesh of rig.parts) {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        mat.color.lerp(targetColor, 0.1);
      }

      const sd = sensorRef.current;
      const jp = sd?.joint_positions;
      const drive = s === "WALKING" ? 1 : s === "EXECUTING" ? 0.4 : 0;
      const fallbackHipL = drive * Math.sin(t * 4);
      const fallbackHipR = -drive * Math.sin(t * 4);
      const fallbackKneeL = drive * Math.max(0, Math.cos(t * 4));
      const fallbackKneeR = drive * Math.max(0, -Math.cos(t * 4));

      rig.joints.hipLeft.rotation.x = jp?.hip_left ?? fallbackHipL;
      rig.joints.hipRight.rotation.x = jp?.hip_right ?? fallbackHipR;
      rig.joints.kneeLeft.rotation.x = -Math.abs(jp?.knee_left ?? fallbackKneeL);
      rig.joints.kneeRight.rotation.x = -Math.abs(jp?.knee_right ?? fallbackKneeR);
      rig.joints.shoulderLeft.rotation.x =
        jp?.shoulder_left ?? -(jp?.hip_left ?? fallbackHipL) * 0.6;
      rig.joints.shoulderRight.rotation.x =
        jp?.shoulder_right ?? -(jp?.hip_right ?? fallbackHipR) * 0.6;

      if (sd?.imu_orientation) {
        rig.group.rotation.x = sd.imu_orientation.x * 0.3;
        rig.group.rotation.z = sd.imu_orientation.y * 0.3;
      }

      rig.group.position.y = s === "IDLE" ? -0.05 + Math.sin(t * 1.5) * 0.02 : 0;

      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).geometry) (obj as THREE.Mesh).geometry.dispose();
        const mat = (obj as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else if (mat) mat.dispose();
      });
    };
  }, []);

  return <div ref={mountRef} className="h-full w-full" />;
}
